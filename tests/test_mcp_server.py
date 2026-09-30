import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import time

import pytest

from research_cli.config import Settings
from research_cli.mcp_server import ApprovalVerifier, Backend


def sign(secret, name, args, nonce="fixture", expires=None):
    payload = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "name": name,
                    "arguments": args,
                    "nonce": nonce,
                    "expires": expires or time.time() + 60,
                }
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    return payload + "." + hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def test_approval_bound_to_arguments_expiry_and_single_use():
    verifier = ApprovalVerifier("test-secret")
    args = {"text": "CPU only"}
    token = sign("test-secret", "remember_research", args)
    assert not verifier.verify(token, "run_experiment", args)
    assert not verifier.verify(token, "remember_research", {"text": "Changed"})
    assert verifier.verify(token, "remember_research", args)
    assert not verifier.verify(token, "remember_research", args)
    assert not verifier.verify(sign("test-secret", "x", {}, expires=time.time() - 1), "x", {})


async def test_backend_approvals_and_structured_errors(tmp_path):
    backend = Backend(tmp_path, Settings(permission="ask"), "secret")
    args = {"kind": "constraint", "status": "active", "text": "CPU only"}
    try:
        assert (await backend.call("remember_research", args))["error"] == "permission_denied"
        result = await backend.call(
            "remember_research", {**args, "_approval": sign("secret", "remember_research", args)}
        )
        assert result["ok"]
        assert (await backend.call("save_evidence", {"quote": "invented"}))[
            "error"
        ] == "invalid_arguments"
        assert all("_approval" not in str(e) for e in backend.store.events("mcp"))
    finally:
        await backend.close()


async def test_experiment_request_id_dedup_and_cleanup(tmp_path):
    backend = Backend(tmp_path, Settings(permission="ask", execution="local"), "secret")
    args = {
        "request_id": "same-run",
        "argv": [sys.executable, "-c", "print('measured')"],
        "cwd": ".",
        "timeout_seconds": 10,
    }
    try:
        first = await backend.call(
            "run_experiment", {**args, "_approval": sign("secret", "run_experiment", args, "one")}
        )
        assert first["ok"], first
        await backend.jobs.tasks[first["result"]["job_id"]]
        again = await backend.call(
            "run_experiment", {**args, "_approval": sign("secret", "run_experiment", args, "two")}
        )
        assert again["result"]["job_id"] == first["result"]["job_id"]
        assert again["result"]["deduplicated"]
        assert len(backend.store.records("jobs")) == 1
        changed = {**args, "argv": [sys.executable, "-c", "print('different')"]}
        rejected = await backend.call(
            "run_experiment",
            {**changed, "_approval": sign("secret", "run_experiment", changed, "three")},
        )
        assert not rejected["ok"]
    finally:
        await backend.close()


async def test_real_stdio_protocol_and_owner_lifecycle(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    (tmp_path / "paper.txt").write_text("A fixture paper says negative results matter.")
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "research_cli.mcp_server",
            "--workspace",
            str(tmp_path),
            "--permission",
            "workspace-write",
            "--offline",
        ],
        env={"PATH": os.environ.get("PATH", "")},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            tools = await client.list_tools()
            assert "remember_research" in {t.name for t in tools.tools}
            assert "search_code" in {t.name for t in tools.tools}
            assert "edit_file" not in {t.name for t in tools.tools}
            imported = await client.call_tool("import_document", {"path": "paper.txt"})
            assert not imported.isError
            assert imported.structuredContent["result"]["chunks"] == 1
            denied = await client.call_tool(
                "run_experiment", {"request_id": "run1", "argv": ["true"]}
            )
            assert denied.isError
            result = await client.call_tool("search_library", {"query": "negative results"})
            assert result.structuredContent["result"]["matches"]
            offline = await client.call_tool("search_papers", {"query": "retrieval"})
            assert offline.isError
    # Transport exit releases ownership; a subsequent process can reopen the same project.
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            status = await client.call_tool("project_status", {})
            assert status.structuredContent["result"]["sources"] == 1


async def test_stdio_exit_cancels_owned_experiment_and_releases_lock(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from research_cli.storage import Store

    secret = "fixture-shutdown"
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "research_cli.mcp_server",
            "--workspace",
            str(tmp_path),
            "--execution",
            "local",
        ],
        env={"RESEARCH_APPROVAL_SECRET": secret, "PATH": os.environ.get("PATH", "")},
    )
    args = {
        "request_id": "exit-test",
        "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
        "cwd": ".",
        "timeout_seconds": 60,
    }
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            result = await client.call_tool(
                "run_experiment", {**args, "_approval": sign(secret, "run_experiment", args)}
            )
            assert not result.isError, result
            job = result.structuredContent["result"]
            assert job["status"] == "running"
    store = Store(tmp_path)
    try:
        assert store.get("jobs", job["job_id"])["status"] == "cancelled"
        with pytest.raises(ProcessLookupError):
            os.kill(job["pid"], 0)
        with store.lock():
            pass
    finally:
        store.close()


async def test_concurrent_retry_cannot_launch_duplicate_processes(tmp_path):
    backend = Backend(tmp_path, Settings(permission="ask", execution="local"), "secret")
    args = {
        "request_id": "parallel",
        "argv": [sys.executable, "-c", "import time; time.sleep(30)"],
        "cwd": ".",
        "timeout_seconds": 40,
    }
    try:
        results = await asyncio.gather(
            *[
                backend.call(
                    "run_experiment",
                    {**args, "_approval": sign("secret", "run_experiment", args, str(i))},
                )
                for i in range(2)
            ]
        )
        assert all(r["ok"] for r in results)
        assert results[0]["result"]["job_id"] == results[1]["result"]["job_id"]
        assert len(backend.jobs.running) == 1
    finally:
        await backend.close()
