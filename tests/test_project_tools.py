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
