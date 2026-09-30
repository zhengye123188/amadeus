from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import signal
import time
from pathlib import Path

from pydantic import Field

from research_cli.storage import encode, identifier
from research_cli.tools import SKIP_DIRS, Args, Empty, Registry, Workspace


class Run(Args):
    argv: list[str] = Field(min_length=1, max_length=100)
    cwd: str = "."
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    request_id: str | None = Field(default=None, min_length=1, max_length=120)


class JobID(Args):
    job_id: str


class JobFile(JobID):
    path: str
    max_chars: int = Field(default=10000, ge=1, le=20000)


class Jobs:
    def __init__(self, registry: Registry):
        self.registry, self.store, self.settings = registry, registry.store, registry.settings
        self.running = {}
        self.tasks = {}
        self.start_lock = asyncio.Lock()
        # Do not signal stale PIDs: another process may now own the number.
        for job in self.store.records("jobs"):
            if job["status"] in {"running", "starting"}:
                job["status"] = "interrupted_unknown"
                job["detail"] = (
                    "CLI owner exited unexpectedly; do not blindly rerun or signal its saved PID."
                )
                self.store.put("jobs", job["job_id"], job)

    def snapshot(self, source: Path, target: Path):
        source = Workspace(self.store.workspace).path(str(source))
        if not source.is_dir():
            raise ValueError("cwd must be a directory")
        target.mkdir()
        total, manifest = 0, {}
        ws = Workspace(self.store.workspace)
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
        async with self.start_lock:
            return await self._start(a)

    async def _start(self, a):
        request_id = a.get("request_id")
        request = {k: a[k] for k in ("argv", "cwd", "timeout_seconds")}
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
        if len(self.running) >= 2:
            raise ValueError("At most two experiments may run concurrently")
        if any("\0" in x or len(x) > 10000 for x in a["argv"]):
            raise ValueError("Invalid command argument")
        timeout = min(a["timeout_seconds"], self.settings.max_job_seconds)
        jid = identifier("job")
        folder = self.store.root / "jobs" / jid
        folder.mkdir()
        work = folder / "work"
        manifest = self.snapshot(Workspace(self.store.workspace).path(a["cwd"]), work)
        (folder / "manifest.json").write_text(encode(manifest))
        digest = hashlib.sha256(encode(manifest).encode()).hexdigest()
        job = {
            "job_id": jid,
            "status": "starting",
            "argv": a["argv"],
            "source_cwd": a["cwd"],
            "backend": self.settings.execution,
            "timeout_seconds": timeout,
            "snapshot_sha256": digest,
            "created": time.time(),
            "exit_code": None,
            "output": "",
            "pid": None,
            "request_id": request_id,
            "request": request,
        }
        self.store.put("jobs", jid, job)
        env = {k: os.environ[k] for k in ["PATH", "SYSTEMROOT", "LANG"] if k in os.environ}
        env["PYTHONUNBUFFERED"] = "1"
        argv = a["argv"]
        if self.settings.execution == "docker":
            if shutil.which("docker") is None:
                job["status"] = "failed"
                job["detail"] = "Docker executable not found"
                self.store.put("jobs", jid, job)
                raise ValueError("Docker is not installed; no fallback to local execution")
            if ":" in str(work):
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
                "--cpus=1",
                "--memory=1g",
                "--tmpfs",
                "/tmp:rw,size=128m",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--volume",
                f"{work}:/work:rw",
                "--workdir",
                "/work",
                self.settings.docker_image,
                *argv,
            ]
            job["image"] = self.settings.docker_image
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=work,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except BaseException:
            job["status"] = "failed"
            self.store.put("jobs", jid, job)
            raise
        job.update(status="running", pid=proc.pid)
        self.store.put("jobs", jid, job)
        self.running[jid] = proc
        self.tasks[jid] = asyncio.create_task(self._collect(jid, proc, timeout))
        # Let the collector enter its try/finally before cancellation can reach it.
        await asyncio.sleep(0)
        return {
            **job,
            "execution_note": "isolated snapshot; outputs stay under job storage. "
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

        async def consume():
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                output.extend(chunk)
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
            self.store.put("jobs", jid, job)
            self.running.pop(jid, None)

    async def status(self, a):
        return self.store.get("jobs", a["job_id"])

    async def cancel(self, a):
        jid = a["job_id"]
        task = self.tasks.get(jid)
        if task and not task.done():
            task.cancel()
            await task
        return self.store.get("jobs", jid)

    async def listing(self, a):
        return self.store.records("jobs")

    async def read_file(self, a):
        self.store.get("jobs", a["job_id"])
        work = self.store.root / "jobs" / a["job_id"] / "work"
        path = (work / a["path"]).resolve()
        if not path.is_relative_to(work) or not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError("Expected a bounded regular file inside the experiment snapshot")
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
            "Run argv (no implicit shell) in a bounded snapshot. Explicit execution permission required. Returns background job ID.",
            Run,
            self.start,
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
            "Stop an experiment started by this CLI; does not signal unknown stale PIDs.",
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
