from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from research_cli.experiments import (
    Experiments,
    ExperimentSpec,
    bounded_file,
    capture_experiment,
    prepare_experiment,
    runtime_environment,
)
from research_cli.job_worker import create_control, worker_request
from research_cli.storage import encode, identifier
from research_cli.tools import SKIP_DIRS, Args, Empty, Registry, Workspace

OWNER_UNCERTAIN_STATES = {"starting", "running", "interrupted_unknown"}


class Run(Args):
    argv: list[str] = Field(min_length=1, max_length=100)
    cwd: str = "."
    timeout_seconds: int = Field(default=60, ge=1, le=604800)
    request_id: str | None = Field(default=None, min_length=1, max_length=120)
    spec: ExperimentSpec | None = Field(
        default=None,
        description="Optional measured experiment: dataset inputs, protocol, seed, parameters, metric definitions and fresh generated output paths.",
    )
    detached: bool = False
    parent_job_id: str | None = Field(default=None, min_length=1, max_length=80)
    expected_parent_snapshot_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def check_ownership(self):
        if not self.detached and self.timeout_seconds > 3600:
            raise ValueError("Foreground experiments are limited to 3600 seconds")
        if self.detached and not self.request_id:
            raise ValueError("Detached experiments require a stable request_id")
        if bool(self.parent_job_id) != bool(self.expected_parent_snapshot_sha256):
            raise ValueError("Resume requires parent_job_id and expected_parent_snapshot_sha256")
        if self.parent_job_id and not self.request_id:
            raise ValueError("Resume requires a new stable request_id")
        return self


class JobID(Args):
    job_id: str


class ProjectCheck(Args):
    argv: list[str] = Field(min_length=1, max_length=100)
    cwd: str = "."
    kind: Literal["test", "build", "lint", "custom"] = "test"
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    request_id: str = Field(
        min_length=1,
        max_length=120,
        description="Stable request ID; reuse it to inspect/retry the same check without executing twice.",
    )


class JobFile(JobID):
    path: str
    max_chars: int = Field(default=10000, ge=1, le=20000)


class Jobs:
    def __init__(self, registry: Registry, recover=True):
        self.registry, self.store, self.settings = registry, registry.store, registry.settings
        self.running = {}
        self.tasks = {}
        self.start_lock = asyncio.Lock()
        # Do not signal stale PIDs: another process may now own the number.
        for job in self.store.records("jobs") if recover else []:
            if job["status"] in {"running", "starting", "interrupted_unknown"}:
                if job.get("detached"):
                    try:
                        worker_request(self.store, job["job_id"], timeout=0.5)
                        continue
                    except (ValueError, OSError):
                        # Recheck after the handshake: the worker may just have finished.
                        job = self.store.get("jobs", job["job_id"])
                        if job["status"] not in {"running", "starting", "interrupted_unknown"}:
                            continue
                detail = (
                    "Owner cannot be verified; inspect state before any new run. "
                    "No saved PID is signalled and no command is replayed."
                )
                self._transition_state(job["job_id"], "interrupted_unknown", detail)

    def _transition_state(self, jid, status, detail, allowed=None):
        """Never overwrite a worker's terminal result with an older owner observation."""
        with self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            current = self.store.get("jobs", jid)
            if current["status"] in (OWNER_UNCERTAIN_STATES if allowed is None else allowed):
                current.update(status=status, detail=detail)
                self.store.db.execute(
                    "UPDATE jobs SET body=?,updated=? WHERE id=?",
                    (encode(current), time.time(), jid),
                )
        return current

    def snapshot(self, source: Path, target: Path, checkpoint=False):
        ws = Workspace(source) if checkpoint else Workspace(self.store.workspace)
        if checkpoint:
            if any(
                path.is_symlink()
                for path in (
                    source,
                    source.parent,
                    source.parent.parent,
                    source.parent.parent.parent,
                )
            ):
                raise ValueError("Checkpoint snapshot may not be a symlink")
        source = ws.path(str(source))
        if not source.is_dir():
            raise ValueError("cwd must be a directory")
        target.mkdir()
        total, manifest = 0, {}
        for root, dirs, files in os.walk(source, followlinks=False):
            dirs[:] = [
                d
                for d in dirs
                if d not in SKIP_DIRS
                and not d.startswith(".")
                and not (Path(root) / d).is_symlink()
            ]
            for name in files:
                p = Path(root) / name
                if p.is_symlink() or name.startswith("."):
                    continue
                try:
                    ws.path(str(p))
                except ValueError:
                    continue
                size = p.stat().st_size
                total += size
                if total > 50_000_000 or len(manifest) >= 5000:
                    raise ValueError(
                        "Experiment snapshot exceeds 50 MB/5000 files; choose a smaller cwd"
                    )
                relative = p.relative_to(source)
                out = target / relative
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, out)
                manifest[str(relative)] = hashlib.sha256(out.read_bytes()).hexdigest()
        return manifest

    async def start(self, a):
        a = Run.model_validate(a).model_dump()
        async with self.start_lock:
            return await self._start(a)

    async def start_check(self, a):
        a = ProjectCheck.model_validate(a).model_dump()
        async with self.start_lock:
            return await self._start(a, workspace_check=True)

    async def _start(self, a, workspace_check=False):
        request_id = a.get("request_id")
        request = {k: a[k] for k in ("argv", "cwd", "timeout_seconds")}
        spec = ExperimentSpec.model_validate(a["spec"]).model_dump() if a.get("spec") else None
        if spec:
            request["spec"] = spec
        if workspace_check:
            request.update(execution_mode="workspace_check", kind=a["kind"])
        if a.get("detached"):
            request["detached"] = True
        if a.get("parent_job_id"):
            request.update(
                parent_job_id=a["parent_job_id"],
                expected_parent_snapshot_sha256=a["expected_parent_snapshot_sha256"],
            )
        if request_id:
            for previous in self.store.records("jobs"):
                if previous.get("request_id") == request_id:
                    if previous.get("request") != request:
                        raise ValueError(
                            "request_id already belongs to different experiment arguments"
                        )
                    return {**previous, "deduplicated": True}
        if self.settings.execution == "disabled":
            raise ValueError(
                "Execution is disabled. Configure docker or explicitly opt into unsandboxed local execution."
            )
        if any("\0" in x or len(x) > 10000 for x in a["argv"]):
            raise ValueError("Invalid command argument")
        timeout = min(a["timeout_seconds"], self.settings.max_job_seconds)
        source = Workspace(self.store.workspace).path(a["cwd"])
        jid = identifier("job")
        folder = self.store.root / "jobs" / jid
        folder.mkdir()
        work = folder / "work"
        resume = None
        try:
            if a.get("parent_job_id"):
                parent = self.store.get("jobs", a["parent_job_id"])
                if parent["status"] not in {
                    "completed",
                    "failed",
                    "cancelled",
                    "timed_out",
                    "output_limit",
                }:
                    raise ValueError(
                        "Resume requires a known finished parent; unknown/live jobs are not replayed"
                    )
                if parent["snapshot_sha256"] != a["expected_parent_snapshot_sha256"]:
                    raise ValueError("Parent snapshot identity does not match expected hash")
                parent_folder = self.store.root / "jobs" / parent["job_id"]
                original_manifest = json.loads(
                    bounded_file(parent_folder, "manifest.json", 10_000_000).read_text()
                )
                if (
                    hashlib.sha256(encode(original_manifest).encode()).hexdigest()
                    != parent["snapshot_sha256"]
                ):
                    raise ValueError("Parent snapshot manifest has changed")
                source = parent_folder / "work"
                resume = {
                    "parent_job_id": parent["job_id"],
                    "parent_snapshot_sha256": parent["snapshot_sha256"],
                    "scope": "Explicit new run from preserved files; program must load its own checkpoint.",
                }
            manifest = self.snapshot(source, work, checkpoint=resume is not None)
            dataset = prepare_experiment(work, spec) if spec else None
        except BaseException:
            shutil.rmtree(folder)
            raise
        (folder / "manifest.json").write_text(encode(manifest))
        digest = hashlib.sha256(encode(manifest).encode()).hexdigest()
        job = {
            "job_id": jid,
            "status": "starting",
            "argv": a["argv"],
            "source_cwd": a["cwd"],
            "backend": self.settings.execution,
            "detached": bool(a.get("detached")),
            "execution_mode": "workspace_check" if workspace_check else "snapshot",
            "kind": a.get("kind", "experiment"),
            "timeout_seconds": timeout,
            "snapshot_sha256": digest,
            "resume": {**resume, "checkpoint_manifest_sha256": digest} if resume else None,
            "created": time.time(),
            "exit_code": None,
            "output": "",
            "pid": None,
            "request_id": request_id,
            "request": request,
            "spec": spec,
            "dataset": dataset,
            "environment": runtime_environment(
                a["argv"],
                self.settings.execution,
                self.settings.docker_image if self.settings.execution == "docker" else None,
            ),
            "resources": {
                "docker_image": self.settings.docker_image,
                "cpus": self.settings.docker_cpus,
                "memory_mb": self.settings.docker_memory_mb,
                "gpus": self.settings.docker_gpus,
                "network": "disabled",
            }
            if self.settings.execution == "docker"
            else {"scope": "Explicit unsandboxed host execution; no hard resource isolation"},
            "experimental_results": {
                "status": "pending" if spec else "not_requested",
                "validation_scope": "Process completion does not validate a scientific claim.",
            },
        }
        if job["detached"]:
            keys = (
                "execution",
                "docker_image",
                "docker_cpus",
                "docker_memory_mb",
                "docker_gpus",
                "max_job_seconds",
                "max_job_output_bytes",
            )
            job["worker_settings"] = {key: getattr(self.settings, key) for key in keys}
        try:
            # Reserve across foreground/detached owners before any side-effecting launch.
            with self.store.db:
                self.store.db.execute("BEGIN IMMEDIATE")
                records = self.store.records("jobs")
                active = [
                    record
                    for record in records
                    if record["status"] in {"starting", "running"}
                    or record.get("detached")
                    and record["status"] == "interrupted_unknown"
                ]
                if len(active) >= 2:
                    raise ValueError(
                        "At most two experiments/checks may run concurrently; verify unknown detached owners first"
                    )
                for previous in records:
                    if request_id and previous.get("request_id") == request_id:
                        if previous.get("request") != request:
                            raise ValueError(
                                "request_id already belongs to different experiment arguments"
                            )
                        shutil.rmtree(folder)
                        return {**previous, "deduplicated": True}
                self.store.db.execute(
                    "INSERT INTO jobs(id,body,updated) VALUES(?,?,?)",
                    (jid, encode(job), time.time()),
                )
        except BaseException:
            if folder.exists():
                shutil.rmtree(folder)
            raise
        if job["detached"]:
            return await self._launch_worker(job)
        return await self._spawn_job(job)

    async def _launch_worker(self, job):
        jid = job["job_id"]
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "LANG") if key in os.environ}
        env.update(PYTHONUNBUFFERED="1", PYTHONPATH=str(Path(__file__).resolve().parent.parent))
        try:
            create_control(self.store, jid)
            # An asyncio subprocess transport can kill its child when the original
            # event loop is collected. Detached owners must not belong to that loop.
            worker = subprocess.Popen(
                [sys.executable, "-m", "research_cli.job_worker", str(self.store.workspace), jid],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
            # Reap while this CLI lives, without delaying interpreter exit. This
            # thread never controls the worker; status/cancel use authenticated IPC.
            threading.Thread(target=worker.wait, name=f"reap-{jid}", daemon=True).start()
        except asyncio.CancelledError:
            self._transition_state(
                jid,
                "interrupted_unknown",
                "Worker launch interrupted; inspect authenticated owner before retrying",
            )
            raise
        except Exception:
            self._transition_state(
                jid, "failed", "Could not launch detached worker", allowed={"starting"}
            )
            raise
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = self.store.get("jobs", jid)
            if current["status"] not in {"starting", "running", "interrupted_unknown"}:
                return {
                    **current,
                    "execution_note": "Detached worker finished; inspect process and measured results separately.",
                }
            try:
                current = await asyncio.to_thread(worker_request, self.store, jid)
                return {
                    **current,
                    "execution_note": "Detached authenticated worker owns this snapshot job; CLI exit does not cancel it.",
                }
            except (ValueError, OSError):
                await asyncio.sleep(0.05)
        return self._transition_state(
            jid,
            "interrupted_unknown",
            "Worker startup identity could not be verified; inspect before retrying. No PID was signalled.",
        )

    async def _spawn_job(self, job):
        jid, timeout = job["job_id"], job["timeout_seconds"]
        work = self.store.root / "jobs" / jid / "work"
        workspace_check = job.get("execution_mode") == "workspace_check"
        try:
            source = (
                Workspace(self.store.workspace).path(job["source_cwd"]) if workspace_check else work
            )
        except (ValueError, OSError):
            self._transition_state(
                jid,
                "failed",
                "Project command directory could not be validated",
                allowed={"starting", "interrupted_unknown"},
            )
            raise
        env = {k: os.environ[k] for k in ["PATH", "SYSTEMROOT", "LANG"] if k in os.environ}
        env["PYTHONUNBUFFERED"] = "1"
        argv = job["argv"]
        if self.settings.execution == "docker":
            if shutil.which("docker") is None:
                self._transition_state(
                    jid,
                    "failed",
                    "Docker executable not found",
                    allowed={"starting", "interrupted_unknown"},
                )
                raise ValueError("Docker is not installed; no fallback to local execution")
            if ":" in str(source):
                self._transition_state(
                    jid,
                    "failed",
                    "Docker mount path contains ':'",
                    allowed={"starting", "interrupted_unknown"},
                )
                raise ValueError("Docker mount path contains ':'")
            argv = [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--name",
                "research-" + jid,
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=128",
                f"--cpus={self.settings.docker_cpus:g}",
                (
                    "--memory=1g"
                    if self.settings.docker_memory_mb == 1024
                    else f"--memory={self.settings.docker_memory_mb}m"
                ),
                "--tmpfs",
                "/tmp:rw,size=128m",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--volume",
                f"{source if workspace_check else work}:/work:rw",
                "--workdir",
                "/work",
                self.settings.docker_image,
                *argv,
            ]
            if self.settings.docker_gpus:
                # Docker's flag itself is CSV-parsed; preserve a device list as one field.
                devices = self.settings.docker_gpus
                argv[2:2] = ["--gpus", "all" if devices == "all" else f'"device={devices}"']
            job["image"] = self.settings.docker_image
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=source if workspace_check else work,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except asyncio.CancelledError:
            self._transition_state(
                jid, "interrupted_unknown", "Process creation interrupted; inspect before retrying"
            )
            raise
        except Exception:
            self._transition_state(
                jid,
                "failed",
                "Could not create command process",
                allowed={"starting", "interrupted_unknown"},
            )
            raise
        job.update(status="running", pid=proc.pid)
        self.store.put("jobs", jid, job)
        self.running[jid] = proc
        self.tasks[jid] = asyncio.create_task(self._collect(jid, proc, timeout))
        # Let the collector enter its try/finally before cancellation can reach it.
        await asyncio.sleep(0)
        return {
            **job,
            "execution_note": (
                "ORIGINAL project directory; test/build commands may modify it. "
                "A pre-run code snapshot is retained for traceability. "
                if workspace_check
                else "isolated snapshot; outputs stay under job storage. "
            )
            + (
                "UNSANDBOXED host process."
                if self.settings.execution == "local"
                else "Docker; no network; image must already be installed."
            ),
        }

    async def _kill(self, jid, proc):
        # A child can hold the output pipe after its parent has exited.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # Drain the killed process's bounded pipe buffer. wait() alone can deadlock
        # when stdout filled after consume() stopped on the output limit.
        await asyncio.wait_for(proc.communicate(), 10)
        if self.settings.execution == "docker":
            try:
                cleanup = await asyncio.create_subprocess_exec(
                    "docker",
                    "rm",
                    "-f",
                    "research-" + jid,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(cleanup.wait(), 10)
            except asyncio.TimeoutError:
                cleanup.kill()
                await cleanup.wait()
            except OSError:
                pass

    async def _collect(self, jid, proc, timeout):
        output = bytearray()
        status = "failed"
        log = self.store.root / "jobs" / jid / "output.log"
        log.write_bytes(b"")
        last_persisted = 0

        async def consume():
            nonlocal last_persisted
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                output.extend(chunk)
                with log.open("ab") as file:
                    file.write(chunk[: max(0, self.settings.max_job_output_bytes - file.tell())])
                if time.monotonic() - last_persisted >= 0.2:
                    current = self.store.get("jobs", jid)
                    current["output"] = bytes(output[-10000:]).decode(errors="replace")
                    self.store.put("jobs", jid, current)
                    last_persisted = time.monotonic()
                if len(output) > self.settings.max_job_output_bytes:
                    raise OverflowError("Output limit")
            await proc.wait()

        try:
            await asyncio.wait_for(consume(), timeout)
            status = "completed" if proc.returncode == 0 else "failed"
        except asyncio.TimeoutError:
            status = "timed_out"
            await self._kill(jid, proc)
        except asyncio.CancelledError:
            status = "cancelled"
            await self._kill(jid, proc)
        except OverflowError:
            status = "output_limit"
            await self._kill(jid, proc)
        except Exception:
            status = "failed"
            await self._kill(jid, proc)
        finally:
            data = bytes(output[: self.settings.max_job_output_bytes])
            (self.store.root / "jobs" / jid / "output.log").write_bytes(data)
            job = self.store.get("jobs", jid)
            job.update(
                status=status,
                exit_code=proc.returncode,
                finished=time.time(),
                output=data.decode(errors="replace")[-10000:],
            )
            if job.get("spec"):
                try:
                    job["experimental_results"] = capture_experiment(self.store, job)
                except (ValueError, OSError) as exc:
                    job["experimental_results"] = {
                        "status": "invalid",
                        "detail": str(exc),
                        "validation_scope": "Process status alone is not measured scientific evidence.",
                    }
            self.store.put("jobs", jid, job)
            self.running.pop(jid, None)

    async def status(self, a):
        jid = a["job_id"]
        job = self.store.get("jobs", jid)
        if (
            job.get("detached")
            and jid not in self.tasks
            and job["status"] in {"starting", "running", "interrupted_unknown"}
        ):
            try:
                return await asyncio.to_thread(worker_request, self.store, jid)
            except (ValueError, OSError) as exc:
                # Completion and socket removal can race the status handshake.
                current = self._transition_state(
                    jid,
                    "interrupted_unknown",
                    "Worker identity cannot be verified; inspect before retrying. No saved PID was signalled.",
                )
                return (
                    {**current, "owner_error": type(exc).__name__}
                    if current["status"] == "interrupted_unknown"
                    else current
                )
        return job

    async def cancel(self, a):
        jid = a["job_id"]
        task = self.tasks.get(jid)
        if task and not task.done():
            task.cancel()
            await task
        elif task is None:
            job = self.store.get("jobs", jid)
            if job.get("detached") and job["status"] in {
                "starting",
                "running",
                "interrupted_unknown",
            }:
                try:
                    return await asyncio.to_thread(worker_request, self.store, jid, "cancel", 15)
                except (ValueError, OSError) as exc:
                    current = self.store.get("jobs", jid)
                    if current["status"] not in {"starting", "running", "interrupted_unknown"}:
                        return current
                    raise ValueError(
                        "Cannot cancel without a verified worker owner; no saved PID was signalled"
                    ) from exc
        return self.store.get("jobs", jid)

    async def listing(self, a):
        return self.store.records("jobs")

    async def read_file(self, a):
        self.store.get("jobs", a["job_id"])
        work = self.store.root / "jobs" / a["job_id"] / "work"
        path = bounded_file(work, a["path"], 2_000_000)
        text = path.read_text()
        return {
            "job_id": a["job_id"],
            "path": a["path"],
            "text": text[: a["max_chars"]],
            "truncated": len(text) > a["max_chars"],
        }

    async def close(self):
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    def register(self):
        self.registry.add(
            "run_experiment",
            "Run argv in a bounded snapshot. Optional spec captures measured output; detached assigns an authenticated worker that survives CLI exit. Explicit parent_job_id/hash starts a new checkpoint-file resume. Execution permission required; exit zero is not scientific validation.",
            Run,
            self.start,
            "execute",
        )
        self.registry.add(
            "run_project_check",
            "Run an explicitly approved test/build/lint argv in the ORIGINAL project directory, with installed dependencies available. May modify the project; retains a pre-run code snapshot. No scientific spec or metric verification. Returns job ID.",
            ProjectCheck,
            self.start_check,
            "execute",
        )
        self.registry.add(
            "job_status",
            "Inspect experiment status, parameters, provenance and output tail.",
            JobID,
            self.status,
        )
        self.registry.add(
            "list_jobs",
            "List experiment records, including failures and interrupted runs.",
            Empty,
            self.listing,
        )
        self.registry.add(
            "cancel_job",
            "Stop an owned foreground job or an authenticated detached worker's live job. Never signals saved unverified PIDs.",
            JobID,
            self.cancel,
            "write",
        )
        self.registry.add(
            "read_job_file",
            "Read a bounded experiment output file such as metrics.json from its snapshot.",
            JobFile,
            self.read_file,
        )
        Experiments(self.registry).register()
