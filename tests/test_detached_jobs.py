import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from research_cli.experiments import verify_experiment
from research_cli.job_worker import control_path, load_control, worker_request
from research_cli.jobs import Jobs, Run
from research_cli.storage import encode


async def finished(jobs, jid, seconds=6):
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        record = await jobs.status({"job_id": jid})
        if record["status"] not in {"starting", "running", "interrupted_unknown"}:
            return record
        await asyncio.sleep(0.03)
    raise AssertionError("Detached job did not finish within the test deadline")


def detached_args(script, request_id="detached-1", timeout=5):
    return {
        "argv": [sys.executable, "-c", script],
        "cwd": ".",
        "timeout_seconds": timeout,
        "request_id": request_id,
        "detached": True,
    }


async def test_detached_job_survives_owner_close_and_reconnects(registry):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    args = detached_args(
        "import time,pathlib; print('started',flush=True); time.sleep(0.4); pathlib.Path('result.txt').write_text('complete')"
    )
    job = await jobs.start(args)
    assert job["detached"] and not jobs.running and not jobs.tasks
    metadata = control_path(registry.store, job["job_id"])
    assert metadata.stat().st_mode & 0o077 == 0
    assert "token" not in encode(job) and "socket" not in encode(job)
    await jobs.close()
    reconnected = Jobs(registry)
    assert (await reconnected.status(job))["status"] != "interrupted_unknown"
    result = await finished(reconnected, job["job_id"])
    assert result["status"] == "completed"
    assert (
        registry.store.root / "jobs" / job["job_id"] / "work" / "result.txt"
    ).read_text() == "complete"
    assert (await reconnected.start(args))["deduplicated"]
    assert "started" in result["output"]


async def test_detached_worker_captures_measured_results_without_api_credentials(
    registry, monkeypatch
):
    registry.settings.execution = "local"
    monkeypatch.setenv("OPENAI_API_KEY", "never-inherit-fixture-key")
    (registry.store.workspace / "input.txt").write_text("sample")
    jobs = Jobs(registry)
    args = detached_args(
        "import os,pathlib; assert 'OPENAI_API_KEY' not in os.environ; assert pathlib.Path('input.txt').read_text()=='sample'; pathlib.Path('metrics.json').write_text('{\"loss\":0.5}')",
        "measured-worker",
    )
    args["spec"] = {
        "group": "worker-capture",
        "variant": "baseline",
        "seed": 0,
        "dataset": {
            "dataset_id": "fixture-input",
            "files": ["input.txt"],
            "split": "test",
            "protocol": "Fixed fixture input for a worker mechanism check",
        },
        "metrics": {
            "loss": {"direction": "minimize", "definition": "Synthetic measured fixture value"}
        },
        "primary_metric": "loss",
    }
    job = await jobs.start(args)
    result = await finished(jobs, job["job_id"])
    assert verify_experiment(registry.store, result)["metrics"] == {"loss": 0.5}
    assert result["dataset"]["sha256"]


async def test_detached_worker_survives_actual_parent_process_exit(registry):
    script = """
import asyncio,json,sys
from pathlib import Path
from research_cli.config import Settings
from research_cli.jobs import Jobs
from research_cli.storage import Store
from research_cli.tools import Registry
async def main():
    store=Store(Path(sys.argv[1]))
    jobs=Jobs(Registry(store,Settings(execution='local')))
    job=await jobs.start({'argv':[sys.executable,'-c',"import time,pathlib; time.sleep(0.7); pathlib.Path('detached.txt').write_text('survived')"], 'cwd':'.', 'timeout_seconds':5, 'request_id':'parent-exit', 'detached':True})
    print(json.dumps({'job_id':job['job_id']}),flush=True)
    await jobs.close()
    store.close()
asyncio.run(main())
"""
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", script, str(registry.store.workspace)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=8,
        check=True,
    )
    jid = json.loads(result.stdout)["job_id"]
    assert result.stderr == ""
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    assert (await finished(jobs, jid))["status"] == "completed"
    assert (registry.store.root / "jobs" / jid / "work" / "detached.txt").read_text() == "survived"


async def test_verified_worker_cancel_and_live_logs(registry):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    job = await jobs.start(
        detached_args("import time; print('live log',flush=True); time.sleep(30)", timeout=30)
    )
    try:
        for _ in range(50):
            status = await jobs.status(job)
            if "live log" in status["output"]:
                break
            await asyncio.sleep(0.02)
        assert "live log" in status["output"]
        result = await Jobs(registry).cancel(job)
        assert result["status"] == "cancelled" and result["exit_code"] is not None
    finally:
        await jobs.cancel(job)


async def test_forged_owner_never_signals_saved_pid(registry, monkeypatch):
    registry.settings.execution = "local"
    registry.store.put(
        "jobs", "unknown", {"job_id": "unknown", "status": "running", "detached": True, "pid": 1}
    )

    def no_signal(*args):
        raise AssertionError("Never signal stale persisted process IDs")

    monkeypatch.setattr(os, "killpg", no_signal)
    jobs = Jobs(registry)
    assert (await jobs.status({"job_id": "unknown"}))["status"] == "interrupted_unknown"
    with pytest.raises(ValueError, match="verified worker"):
        await jobs.cancel({"job_id": "unknown"})


async def test_actual_worker_crash_preserves_unknown_outcome_without_replay(registry, monkeypatch):
    registry.settings.execution = "local"
    spawned = []
    original = asyncio.create_subprocess_exec

    async def track_spawn(*args, **kwargs):
        proc = await original(*args, **kwargs)
        if "research_cli.job_worker" in args:
            spawned.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", track_spawn)
    jobs = Jobs(registry)
    job = await jobs.start(detached_args("import time; time.sleep(0.5)", "crash-worker"))
    assert spawned and (await jobs.status(job))["status"] == "running"
    # Fault injection targets our freshly spawned process object, never a saved PID.
    spawned[0].kill()
    await spawned[0].wait()
    control = load_control(registry.store, job["job_id"])
    try:
        reconnected = Jobs(registry)
        assert (await reconnected.status(job))["status"] == "interrupted_unknown"
        with pytest.raises(ValueError, match="verified worker"):
            await reconnected.cancel(job)
        assert len(registry.store.records("jobs")) == 1
        assert (
            await reconnected.start(detached_args("import time; time.sleep(0.5)", "crash-worker"))
        )["deduplicated"]
        await asyncio.sleep(0.55)  # The deliberately short orphan child exits on its own.
    finally:
        Path(control["socket"]).unlink(missing_ok=True)


async def test_wrong_control_secret_cannot_cancel_real_worker(registry):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    job = await jobs.start(detached_args("import time; time.sleep(30)", timeout=30))
    path = control_path(registry.store, job["job_id"])
    original = path.read_text()
    try:
        control = json.loads(original)
        control["token"] = "0" * 64
        path.write_text(encode(control))
        with pytest.raises(ValueError, match="verified worker"):
            await jobs.cancel(job)
        path.write_text(original)
        assert (await jobs.status(job))["status"] == "running"
    finally:
        path.write_text(original)
        assert (await jobs.cancel(job))["status"] == "cancelled"


async def test_concurrency_cap_counts_detached_and_project_checks(registry):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    first = await jobs.start(detached_args("import time; time.sleep(30)", "worker-one", 30))
    second = await jobs.start(detached_args("import time; time.sleep(30)", "worker-two", 30))
    try:
        with pytest.raises(ValueError, match="At most two"):
            await jobs.start_check(
                {"argv": [sys.executable, "--version"], "request_id": "third-check"}
            )
        assert len(registry.store.records("jobs")) == 2
    finally:
        await jobs.cancel(first)
        await jobs.cancel(second)


async def test_explicit_resume_copies_checkpoint_into_new_snapshot(registry):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    parent = await jobs.start(
        {
            "argv": [
                sys.executable,
                "-c",
                "import pathlib; pathlib.Path('checkpoint.json').write_text('{\"epoch\":3}'); raise SystemExit(2)",
            ],
            "cwd": ".",
            "timeout_seconds": 5,
            "request_id": "checkpoint-parent",
        }
    )
    await jobs.tasks[parent["job_id"]]
    args = detached_args(
        "import json,pathlib; checkpoint=json.loads(pathlib.Path('checkpoint.json').read_text()); assert checkpoint['epoch']==3; pathlib.Path('resumed.json').write_text('{\"epoch\":4}')",
        "checkpoint-resume",
    )
    args.update(
        parent_job_id=parent["job_id"], expected_parent_snapshot_sha256=parent["snapshot_sha256"]
    )
    child = await jobs.start(args)
    done = await finished(jobs, child["job_id"])
    assert done["status"] == "completed"
    assert child["resume"]["parent_job_id"] == parent["job_id"]
    assert child["snapshot_sha256"] != parent["snapshot_sha256"]
    assert (registry.store.root / "jobs" / child["job_id"] / "work" / "resumed.json").exists()
    assert not (registry.store.root / "jobs" / parent["job_id"] / "work" / "resumed.json").exists()
    with pytest.raises(ValueError, match="Parent snapshot identity"):
        await jobs.start(
            {**args, "request_id": "wrong-parent", "expected_parent_snapshot_sha256": "0" * 64}
        )


async def test_unknown_jobs_are_not_automatically_resumed(registry):
    registry.settings.execution = "local"
    registry.store.put(
        "jobs",
        "unknown",
        {"job_id": "unknown", "status": "interrupted_unknown", "snapshot_sha256": "0" * 64},
    )
    jobs = Jobs(registry)
    with pytest.raises(ValueError, match="known finished parent"):
        await jobs.start(
            {
                **detached_args("pass"),
                "parent_job_id": "unknown",
                "expected_parent_snapshot_sha256": "0" * 64,
            }
        )


def test_long_deadlines_require_detached_request_and_resume_identity():
    assert (
        Run(
            argv=["python", "train.py"], timeout_seconds=86400, detached=True, request_id="long"
        ).timeout_seconds
        == 86400
    )
    with pytest.raises(ValueError, match="Foreground"):
        Run(argv=["python", "train.py"], timeout_seconds=86400)
    with pytest.raises(ValueError, match="stable request_id"):
        Run(argv=["python", "train.py"], detached=True)
    with pytest.raises(ValueError, match="Resume requires"):
        Run(argv=["python", "train.py"], parent_job_id="parent")


def test_control_requests_require_an_authenticated_owner(registry):
    with pytest.raises(ValueError, match="private worker control"):
        worker_request(registry.store, "missing")
    with pytest.raises(ValueError, match="private worker control"):
        load_control(registry.store, "missing")


async def test_launch_deadline_cannot_overwrite_concurrently_finished_worker(registry, monkeypatch):
    from types import SimpleNamespace

    import research_cli.jobs as module

    record = {"job_id": "deadline-race", "status": "starting", "detached": True}
    registry.store.put("jobs", record["job_id"], record)
    ticks = iter([0.0, 0.0, 6.0])
    monkeypatch.setattr(
        module, "time", SimpleNamespace(monotonic=lambda: next(ticks), time=module.time.time)
    )
    monkeypatch.setattr(module, "create_control", lambda *args: None)

    async def fake_spawn(*args, **kwargs):
        return None

    async def same_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    def failed_handshake_after_completion(store, jid):
        store.put("jobs", jid, {**record, "status": "completed", "exit_code": 0, "finished": 1})
        raise OSError("Socket was removed on completion")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(asyncio, "to_thread", same_thread)
    monkeypatch.setattr(module, "worker_request", failed_handshake_after_completion)
    result = await Jobs(registry, recover=False)._launch_worker(record)
    assert result["status"] == "completed"
    assert registry.store.get("jobs", record["job_id"])["status"] == "completed"


@pytest.mark.parametrize("path", ["startup", "status"])
async def test_failed_owner_handshake_preserves_new_terminal_state(registry, monkeypatch, path):
    import research_cli.jobs as module

    record = {"job_id": "owner-race", "status": "running", "detached": True}
    registry.store.put("jobs", record["job_id"], record)

    def failed_handshake_after_completion(store, jid, **kwargs):
        store.put("jobs", jid, {**record, "status": "failed", "exit_code": 2, "finished": 1})
        raise OSError("Worker exited after recording its outcome")

    async def same_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(module, "worker_request", failed_handshake_after_completion)
    monkeypatch.setattr(asyncio, "to_thread", same_thread)
    jobs = Jobs(registry, recover=path == "startup")
    result = await jobs.status(record)
    assert result["status"] == "failed" and result["exit_code"] == 2


async def test_original_worker_can_claim_interrupted_startup_once(registry):
    from research_cli.config import Settings
    from research_cli.job_worker import create_control, own_job

    registry.settings.execution = "local"
    jid = "interrupted-startup"
    folder = registry.store.root / "jobs" / jid
    (folder / "work").mkdir(parents=True)
    record = {
        "job_id": jid,
        "status": "interrupted_unknown",
        "detached": True,
        "argv": [sys.executable, "-c", "print('original owner completed')"],
        "timeout_seconds": 3,
        "source_cwd": ".",
        "execution_mode": "snapshot",
        "worker_settings": Settings(execution="local").model_dump(),
    }
    registry.store.put("jobs", jid, record)
    create_control(registry.store, jid)
    await own_job(registry.store.workspace, jid)
    completed = registry.store.get("jobs", jid)
    assert completed["status"] == "completed" and completed["worker_claimed"]
    assert "original owner completed" in completed["output"]
    completed["status"] = "interrupted_unknown"
    registry.store.put("jobs", jid, completed)
    with pytest.raises(ValueError, match="only claim"):
        await own_job(registry.store.workspace, jid)
    assert registry.store.get("jobs", jid)["status"] == "interrupted_unknown"
