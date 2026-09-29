import json
import os

import pytest
from conftest import approve, deny

from research_cli.tools import Empty, Workspace


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        ".env",
        ".git/config",
        ".research/state.sqlite3",
        "research.toml",
        "private.pem",
    ],
)
async def test_private_and_escaped_paths(registry, path):
    result = await registry.invoke("read_file", json.dumps({"path": path}), approve)
    assert result["ok"] is False


def test_symlink_escape_and_hardlink_write(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    (root / "link.txt").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        Workspace(root).read("link.txt")
    os.link(outside, root / "hard.txt")
    with pytest.raises(ValueError, match="hard-linked"):
        Workspace(root).path("hard.txt", write=True)


async def test_edit_approval_hash_and_recovery_artifact(registry, tmp_path):
    path = tmp_path / "code.py"
    path.write_text("value = 1\n")
    first = await registry.invoke("read_file", '{"path":"code.py"}', deny)
    args = dict(
        path="code.py", old_text="1", new_text="2", expected_sha256=first["result"]["sha256"]
    )
    rejected = await registry.invoke("edit_file", json.dumps(args), deny)
    assert rejected["error"] == "permission_denied"
    assert path.read_text() == "value = 1\n"
    changed = await registry.invoke("edit_file", json.dumps(args), approve)
    assert changed["ok"]
    assert path.read_text() == "value = 2\n"
    assert "-value = 1" in changed["result"]["diff"]
    backup = registry.store.read_artifact(changed["result"]["before"]["artifact_id"])
    assert backup["text"] == "value = 1\n"
    stale = await registry.invoke("edit_file", json.dumps(args), approve)
    assert not stale["ok"] and "changed" in stale["detail"]
    assert path.read_text() == "value = 2\n"


@pytest.mark.parametrize(
    "arguments", ['{"path":1}', '{"path":"x","extra":1}', "{bad", '{"path":"x","start_line":false}']
)
async def test_malformed_arguments_are_observations(registry, arguments):
    result = await registry.invoke("read_file", arguments, approve)
    assert result["error"] == "invalid_arguments"


async def test_policy_is_enforced_outside_model(registry):
    registry.settings.permission = "read-only"
    args = json.dumps(dict(path="new.txt", old_text="", new_text="new", expected_sha256="new"))
    result = await registry.invoke("edit_file", args, approve)
    assert result["error"] == "permission_denied"
    registry.settings.permission = "workspace-write"
    result = await registry.invoke("edit_file", args, deny)
    assert result["ok"]

    async def forbidden(a):
        raise AssertionError("Must not run")

    registry.add("network", "network", Empty, forbidden, network=True)
    registry.settings.allow_network = False
    assert (await registry.invoke("network", "{}", approve))["error"] == "network_disabled"
    registry.add("execution", "execution", Empty, forbidden, "execute")
    assert (await registry.invoke("execution", "{}", deny))["error"] == "permission_denied"


async def test_large_result_has_recoverable_full_artifact(registry):
    text = "论文证据" * 5000

    async def large(a):
        return {"text": text}

    registry.add("large", "large", Empty, large)
    result = (await registry.invoke("large", "{}", deny))["result"]
    assert result["truncated"]
    full = registry.store.read_artifact(result["artifact_id"], limit=100000)
    assert json.loads(full["text"])["text"] == text


def test_workspace_lock_and_state_symlink(store, tmp_path):
    with store.lock(), pytest.raises(ValueError, match="Another research"):
        with store.lock():
            pass
