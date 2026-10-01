import hashlib
import json
import sqlite3
import zipfile

import pytest

from research_cli.maintenance import backup_project, restore_project
from research_cli.storage import SCHEMA_VERSION, Store


def test_v02_database_migrates_without_changing_ids_or_bodies(tmp_path):
    root = tmp_path / ".research"
    root.mkdir()
    database = sqlite3.connect(root / "state.sqlite3")
    database.execute("CREATE TABLE sources(id TEXT PRIMARY KEY,body TEXT,created REAL)")
    database.execute("INSERT INTO sources VALUES(?,?,?)", ("paper_old", '{"title":"已有论文"}', 42))
    database.commit()
    database.close()
    store = Store(tmp_path)
    try:
        assert store.get("sources", "paper_old") == {"title": "已有论文"}
        assert store.database_info() == {
            "schema_version": SCHEMA_VERSION,
            "supported_schema_version": SCHEMA_VERSION,
            "integrity": "ok",
        }
        assert store.db.execute("SELECT created FROM sources").fetchone()[0] == 42
    finally:
        store.close()


def test_newer_database_rejected_before_existing_content_changes(tmp_path):
    store = Store(tmp_path)
    store.db.execute("PRAGMA user_version=999")
    store.db.commit()
    store.close()
    with pytest.raises(ValueError, match="newer Research CLI"):
        Store(tmp_path)
    database = sqlite3.connect(tmp_path / ".research/state.sqlite3")
    assert database.execute("PRAGMA user_version").fetchone()[0] == 999
    database.close()


def test_wal_backup_restore_keeps_evidence_artifacts_and_job_files(tmp_path):
    source = tmp_path / "source"
    store = Store(source)
    try:
        store.put("sources", "paper_one", {"title": "可恢复记录"})
        artifact = store.artifact("a real result")
        folder = store.root / "jobs/job_old/work"
        folder.mkdir(parents=True)
        (folder / "result.json").write_text('{"accuracy":0.75}')
        backup = backup_project(store)
        assert hashlib.sha256(open(backup["path"], "rb").read()).hexdigest() == backup["sha256"]
        destination = tmp_path / "restored"
        restored = restore_project(type(folder)(backup["path"]), destination)
        assert restored["integrity"] == "ok"
        other = Store(destination)
        try:
            assert other.get("sources", "paper_one")["title"] == "可恢复记录"
            assert other.read_artifact(artifact["artifact_id"])["text"] == "a real result"
            assert (other.root / "jobs/job_old/work/result.json").read_text() == '{"accuracy":0.75}'
        finally:
            other.close()
        with pytest.raises(ValueError, match="never overwritten"):
            restore_project(type(folder)(backup["path"]), destination)
    finally:
        store.close()


def test_archive_tamper_and_traversal_never_create_project_state(tmp_path):
    store = Store(tmp_path / "original")
    try:
        backup = backup_project(store)
    finally:
        store.close()
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(backup["path"]) as archive, zipfile.ZipFile(broken, "w") as target:
        for name in archive.namelist():
            target.writestr(name, b"corrupt" if name == "state.sqlite3" else archive.read(name))
    with pytest.raises(ValueError, match="checksum"):
        restore_project(broken, tmp_path / "broken-target")
    assert not (tmp_path / "broken-target/.research").exists()
    malicious = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../outside", "escape")
        archive.writestr("manifest.json", json.dumps({}))
    with pytest.raises(ValueError, match="Unsafe"):
        restore_project(malicious, tmp_path / "safe-target")
    assert not (tmp_path / "outside").exists()


def test_backup_refuses_live_jobs_and_symlink_artifacts(store, tmp_path):
    store.put("jobs", "job_live", {"status": "running"})
    with pytest.raises(ValueError, match="running jobs"):
        backup_project(store)
    store.put("jobs", "job_live", {"status": "completed"})
    (store.root / "artifacts/private").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="Symlinks"):
        backup_project(store)
