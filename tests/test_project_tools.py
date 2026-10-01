import json
import shutil

import pytest

from research_cli.project_tools import CheckpointCreate, ProjectTools, SearchProject


async def test_checkpoint_restores_selected_changes_and_removes_planned_new_file(registry):
    tools = ProjectTools(registry)
    root = registry.store.workspace
    (root / "model.py").write_text("print('baseline')\n")
    created = await tools.create(CheckpointCreate(paths=["model.py", "new.py"]).model_dump())
    (root / "model.py").write_text("print('candidate')\n")
    (root / "new.py").write_text("new code\n")
    inspected = await tools.inspect(created)
    assert "candidate" in inspected["files"]["model.py"]["diff"]
    await tools.restore(
        {
            "checkpoint_id": created["checkpoint_id"],
            "expected_current_sha256": inspected["expected_current_sha256"],
        }
    )
    assert (root / "model.py").read_text() == "print('baseline')\n"
    assert not (root / "new.py").exists()


async def test_stale_restore_does_not_touch_any_checkpoint_file(registry):
    tools = ProjectTools(registry)
    root = registry.store.workspace
    for name in ("first.py", "second.py"):
        (root / name).write_text("before\n")
    created = await tools.create(CheckpointCreate(paths=["first.py", "second.py"]).model_dump())
    for name in ("first.py", "second.py"):
        (root / name).write_text("after\n")
    inspected = await tools.inspect(created)
    (root / "second.py").write_text("user's later edit\n")
    with pytest.raises(ValueError, match="changed since"):
        await tools.restore(
            {
                "checkpoint_id": created["checkpoint_id"],
                "expected_current_sha256": inspected["expected_current_sha256"],
            }
        )
    assert (root / "first.py").read_text() == "after\n"
    assert (root / "second.py").read_text() == "user's later edit\n"


async def test_corrupted_checkpoint_payload_does_not_partially_restore(registry):
    tools = ProjectTools(registry)
    root = registry.store.workspace
    for name in ("first.py", "second.py"):
        (root / name).write_text("before\n")
    created = await tools.create(CheckpointCreate(paths=["first.py", "second.py"]).model_dump())
    for name in ("first.py", "second.py"):
        (root / name).write_text("after\n")
    inspected = await tools.inspect(created)
    body = tools.get(created["checkpoint_id"])
    body["files"]["second.py"]["sha256"] = "bad-hash"
    registry.store.db.execute(
        "UPDATE code_checkpoints SET body=? WHERE id=?",
        (json.dumps(body), created["checkpoint_id"]),
    )
    registry.store.db.commit()
    with pytest.raises(ValueError, match="checksum"):
        await tools.restore(
            {
                "checkpoint_id": created["checkpoint_id"],
                "expected_current_sha256": inspected["expected_current_sha256"],
            }
        )
    assert (root / "first.py").read_text() == "after\n"


async def test_checkpoint_and_search_do_not_read_private_or_escaping_files(registry, tmp_path):
    tools = ProjectTools(registry)
    root = registry.store.workspace
    (root / ".env").write_text("private secret")
    outside = tmp_path.parent / (tmp_path.name + "-external")
    outside.write_text("external secret")
    try:
        (root / "escape.txt").symlink_to(outside)
        with pytest.raises(ValueError, match="outside"):
            await tools.create(CheckpointCreate(paths=["escape.txt"]).model_dump())
        with pytest.raises(ValueError, match="Private"):
            await tools.create(CheckpointCreate(paths=[".env"]).model_dump())
        result = await tools.search(SearchProject(query="secret").model_dump())
        assert result["matches"] == []
    finally:
        outside.unlink()


async def test_search_globs_pagination_and_python_symbols(registry):
    tools = ProjectTools(registry)
    root = registry.store.workspace
    (root / "model.py").write_text(
        "import math\nclass Model:\n    def predict(self):\n        return math.sqrt(4)\n"
    )
    (root / "notes.txt").write_text("Model predict Model predict")
    result = await tools.search(SearchProject(query="model", globs=["*.py"], limit=1).model_dump())
    assert result["matches"][0]["path"] == "model.py"
    result = await tools.search(SearchProject(query="predict", limit=1, offset=1).model_dump())
    assert result["matches"][0]["path"] == "notes.txt"
    symbols = await tools.symbols({"path": "model.py"})
    assert [entry.get("name") for entry in symbols["symbols"] if "name" in entry] == [
        "Model",
        "predict",
    ]
    assert symbols["symbols"][0]["kind"] == "import"
    assert not (await tools.symbols({"path": "notes.txt"}))["supported"]


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
async def test_regex_search_uses_ripgrep_with_literal_arguments(registry):
    tools = ProjectTools(registry)
    (registry.store.workspace / "model.py").write_text("def predict(x):\n    return x\n")
    result = await tools.search(SearchProject(query=r"def\s+predict", regex=True).model_dump())
    assert result["backend"] == "ripgrep"
    assert result["matches"][0]["line"] == 1
    with pytest.raises(ValueError, match="Invalid search"):
        await tools.search(SearchProject(query="[", regex=True).model_dump())


async def test_literal_search_reads_one_file_at_a_time_and_stops_after_page(registry, monkeypatch):
    tools = ProjectTools(registry)
    for name in ("first.txt", "second.txt", "third.txt"):
        (registry.store.workspace / name).write_text("match\nmatch\n")
    original = tools.ws.read
    calls = []

    def read(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(tools.ws, "read", read)
    result = await tools.search(SearchProject(query="match", limit=1).model_dump())
    assert result["matches"][0]["path"] == "first.txt"
    assert len(calls) == 1
    assert result["next_offset"] == 1


async def test_search_reports_scan_byte_limit_without_reading_all_inputs(registry, monkeypatch):
    import research_cli.project_tools as module

    tools = ProjectTools(registry)
    (registry.store.workspace / "first.txt").write_text("no match")
    (registry.store.workspace / "second.txt").write_text("no match")
    monkeypatch.setattr(module, "MAX_SEARCH_BYTES", 8)
    result = await tools.search(SearchProject(query="absent").model_dump())
    assert result["scan_bytes"] == 8
    assert result["scan_byte_limit"] == 8
    assert result["truncated"]


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
async def test_regex_uses_bounded_chunks_without_loading_file_text(registry, monkeypatch):
    import os

    import research_cli.project_tools as module

    tools = ProjectTools(registry)
    for number in range(8):
        (registry.store.workspace / (str(number) + "x" * 70 + ".txt")).write_text("needle\n")

    def no_read(_path):
        raise AssertionError("Regex search must retain validated paths only")

    monkeypatch.setattr(tools.ws, "read", no_read)
    monkeypatch.setattr(module, "MAX_RG_ARGUMENT_BYTES", 500)
    original = module.asyncio.create_subprocess_exec
    calls = []

    async def spawn(*args, **kwargs):
        assert sum(len(os.fsencode(arg)) + 1 for arg in args) <= 500
        assert "OPENAI_API_KEY" not in kwargs["env"]
        calls.append(args)
        return await original(*args, **kwargs)

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    result = await tools.search(SearchProject(query="needle", regex=True, limit=20).model_dump())
    assert len(result["matches"]) == 8
    assert len(calls) > 1


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
async def test_regex_pagination_can_go_beyond_one_hundred_matches(registry):
    tools = ProjectTools(registry)
    (registry.store.workspace / "many.txt").write_text("needle\n" * 150)
    result = await tools.search(
        SearchProject(query="needle", regex=True, offset=120, limit=10).model_dump()
    )
    assert result["matches"][0]["line"] == 121
    assert len(result["matches"]) == 10
    assert result["next_offset"] == 130
