import asyncio
import json
import sys

import pytest

from research_cli.jobs import Jobs


async def test_local_experiment_snapshot_metrics_and_secret_filter(registry, tmp_path, monkeypatch):
    registry.settings.execution = "local"
    (tmp_path / "input.txt").write_text("source")
    (tmp_path / ".env").write_text("secret")
    (tmp_path / "research.toml").write_text("private")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-inherit")
    jobs = Jobs(registry)
    try:
        result = await jobs.start(
            {
                "argv": [
                    sys.executable,
                    "-c",
                    "import os,pathlib,json; assert 'OPENAI_API_KEY' not in os.environ; assert not pathlib.Path('.env').exists(); pathlib.Path('metrics.json').write_text(json.dumps({'accuracy':0.5})); print('done')",
                ],
                "cwd": ".",
                "timeout_seconds": 5,
            }
        )
        await jobs.tasks[result["job_id"]]
        status = await jobs.status(result)
        assert status["status"] == "completed" and status["exit_code"] == 0
        assert "done" in status["output"]
        metrics = await jobs.read_file(
            {"job_id": result["job_id"], "path": "metrics.json", "max_chars": 1000}
        )
        assert json.loads(metrics["text"])["accuracy"] == 0.5
        assert not (tmp_path / "metrics.json").exists()
        manifest = json.loads(
            (registry.store.root / "jobs" / result["job_id"] / "manifest.json").read_text()
        )
        assert set(manifest) == {"input.txt"}
    finally:
        await jobs.close()


@pytest.mark.parametrize("mode", ["timeout", "cancel", "overflow", "failure"])
async def test_job_failure_modes_terminate_and_record(registry, mode):
    registry.settings.execution = "local"
    registry.settings.max_job_output_bytes = 1024
    jobs = Jobs(registry)
    scripts = {
        "timeout": "import time; time.sleep(60)",
        "cancel": "import time; time.sleep(60)",
        "overflow": "print('x'*10000000)",
        "failure": "raise SystemExit(3)",
    }
    try:
        result = await jobs.start(
            {"argv": [sys.executable, "-c", scripts[mode]], "cwd": ".", "timeout_seconds": 1}
        )
        if mode == "cancel":
            await asyncio.sleep(0.02)
            await jobs.cancel(result)
        await asyncio.wait_for(jobs.tasks[result["job_id"]], 5)
        job = await jobs.status(result)
        assert (
            job["status"]
            == {
                "timeout": "timed_out",
                "cancel": "cancelled",
                "overflow": "output_limit",
                "failure": "failed",
            }[mode]
        )
        assert job["exit_code"] is not None
        assert not jobs.running
    finally:
        await jobs.close()


async def test_disabled_execution_never_spawns(registry):
    jobs = Jobs(registry)
    with pytest.raises(ValueError, match="disabled"):
        await jobs.start({"argv": ["python", "--version"], "cwd": ".", "timeout_seconds": 1})
    assert not registry.store.records("jobs")


async def test_restart_marks_stale_job_unknown_without_killing_pid(registry):
    registry.store.put("jobs", "old", {"job_id": "old", "status": "running", "pid": 1})
    jobs = Jobs(registry)
    assert (await jobs.status({"job_id": "old"}))["status"] == "interrupted_unknown"


async def test_immediate_shutdown_cleans_owned_job(registry):
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    result = await jobs.start(
        {
            "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
            "cwd": ".",
            "timeout_seconds": 60,
        }
    )
    await jobs.close()
    assert (await jobs.status(result))["status"] == "cancelled"
    assert not jobs.running


async def test_docker_flags_and_no_implicit_shell(registry, monkeypatch):
    import shutil
    from types import SimpleNamespace

    registry.settings.execution = "docker"
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/docker")
    calls = []
    stream = asyncio.StreamReader()
    stream.feed_eof()

    async def wait():
        return 0

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(pid=999999999, returncode=0, stdout=stream, wait=wait)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    jobs = Jobs(registry)
    result = await jobs.start({"argv": ["python", "run.py"], "cwd": ".", "timeout_seconds": 5})
    await jobs.tasks[result["job_id"]]
    argv, kwargs = calls[0]
    for option in [
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=128",
        "--memory=1g",
        "--cpus=1",
        "--pull=never",
    ]:
        assert option in argv
    assert argv[-2:] == ("python", "run.py")
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert kwargs["start_new_session"] is True
    assert (await jobs.status(result))["status"] == "completed"


async def test_missing_docker_never_falls_back_to_host(registry, monkeypatch):
    import shutil

    registry.settings.execution = "docker"
    monkeypatch.setattr(shutil, "which", lambda name: None)
    jobs = Jobs(registry)
    with pytest.raises(ValueError, match="no fallback"):
        await jobs.start({"argv": ["python", "--version"], "cwd": ".", "timeout_seconds": 1})
    assert registry.store.records("jobs")[0]["status"] == "failed"


async def test_project_check_uses_original_cwd_dependencies_and_snapshot(registry, tmp_path):
    registry.settings.execution = "local"
    (tmp_path / "source.py").write_text("print('original')")
    dependencies = tmp_path / "node_modules" / "fixture"
    dependencies.mkdir(parents=True)
    (dependencies / "package.json").write_text('{"name":"fixture"}')
    jobs = Jobs(registry)
    args = {
        "argv": [
            sys.executable,
            "-c",
            "import pathlib; assert pathlib.Path('node_modules/fixture/package.json').exists(); pathlib.Path('checked.txt').write_text('passed'); print('project check passed')",
        ],
        "cwd": ".",
        "kind": "test",
        "timeout_seconds": 5,
        "request_id": "project-check-1",
    }
    result = await jobs.start_check(args)
    await jobs.tasks[result["job_id"]]
    job = await jobs.status(result)
    assert job["status"] == "completed"
    assert job["execution_mode"] == "workspace_check"
    assert job["experimental_results"]["status"] == "not_requested"
    assert "ORIGINAL" in result["execution_note"]
    assert (tmp_path / "checked.txt").read_text() == "passed"
    work = registry.store.root / "jobs" / job["job_id"] / "work"
    assert (work / "source.py").read_text() == "print('original')"
    assert not (work / "checked.txt").exists()
    assert not (work / "node_modules").exists()
    assert (await jobs.start_check(args))["deduplicated"]
    with pytest.raises(ValueError, match="different experiment arguments"):
        await jobs.start(
            {key: args[key] for key in ("argv", "cwd", "timeout_seconds", "request_id")}
        )


async def test_project_check_cannot_smuggle_scientific_spec_or_bypass_execution(registry):
    jobs = Jobs(registry)
    args = {"argv": ["python", "--version"], "request_id": "check-disabled"}
    with pytest.raises(ValueError, match="disabled"):
        await jobs.start_check(args)
    with pytest.raises(ValueError, match="Extra inputs"):
        await jobs.start_check({**args, "spec": {}})
    assert not registry.store.records("jobs")


async def test_project_check_obeys_read_only_permission(registry):
    from research_cli.storage import encode

    registry.settings.permission = "read-only"
    registry.settings.execution = "local"
    jobs = Jobs(registry)
    jobs.register()

    async def approve(name, args):
        raise AssertionError("read-only mode should reject before requesting approval")

    result = await registry.invoke(
        "run_project_check",
        encode({"argv": [sys.executable, "--version"], "request_id": "read-only-check"}),
        approve,
    )
    assert not result["ok"]
    assert not registry.store.records("jobs")
