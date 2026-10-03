import hashlib
import json
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from research_cli.maintenance import backup_project, restore_project
from research_cli.storage import SCHEMA_VERSION, Store


def test_concurrent_first_open_migrates_once_and_preserves_both_sessions(tmp_path, monkeypatch):
    root = tmp_path / ".research"
    root.mkdir()
    with sqlite3.connect(root / "state.sqlite3") as database:
        database.execute("PRAGMA journal_mode=WAL")
    database.close()
    ready = Barrier(2)
    connect = sqlite3.connect

    class ConcurrentConnection(sqlite3.Connection):
        def executescript(self, script):
            result = super().executescript(script)
            # Both independent connections have observed the unmigrated database.
            ready.wait(timeout=10)
            return result

    def open_store(title):
        store = Store(tmp_path)
        try:
            return store.create_session(title)
        finally:
            store.close()

    with monkeypatch.context() as patch:
        patch.setattr(
            sqlite3,
            "connect",
            lambda *args, **kwargs: connect(*args, factory=ConcurrentConnection, **kwargs),
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(open_store, "memory")
            second = pool.submit(open_store, "backend")
            session_ids = {first.result(timeout=15), second.result(timeout=15)}
    store = Store(tmp_path)
    try:
        assert {item["id"] for item in store.sessions()} == session_ids
        assert {item["title"] for item in store.sessions()} == {"memory", "backend"}
        assert [row[0] for row in store.db.execute("SELECT version FROM schema_migrations")] == [1]
        assert store.database_info()["schema_version"] == SCHEMA_VERSION
        assert store.database_info()["integrity"] == "ok"
    finally:
        store.close()


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
    with pytest.raises(ValueError, match="newer Amadeus"):
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
        ledger = '{"model":"fixture","tokens":42}\n'
        (store.root / "usage.jsonl").write_text(ledger)
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
            assert (other.root / "usage.jsonl").read_text() == ledger
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
        archive.writestr("state.sqlite3", b"")
    with pytest.raises(ValueError, match="Unsafe"):
        restore_project(malicious, tmp_path / "safe-target")
    assert not (tmp_path / "outside").exists()


def test_manifest_only_or_wrong_application_database_never_installs(tmp_path):
    archive_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", "{}")
    with pytest.raises(ValueError, match="requires its database"):
        restore_project(archive_path, tmp_path / "empty-target")
    assert not (tmp_path / "empty-target/.research").exists()
    database_path = tmp_path / "unrelated.sqlite3"
    database = sqlite3.connect(database_path)
    database.execute("CREATE TABLE unrelated(id INTEGER)")
    database.commit()
    database.close()
    data = database_path.read_bytes()
    manifest = {
        "format": "research-project-v1",
        "schema_version": 1,
        "files": {
            "state.sqlite3": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        },
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("state.sqlite3", data)
    with pytest.raises(ValueError, match="compatible project schema"):
        restore_project(archive_path, tmp_path / "wrong-target")
    assert not (tmp_path / "wrong-target/.research").exists()


def test_backup_refuses_live_jobs_and_symlink_artifacts(store, tmp_path):
    store.put("jobs", "job_live", {"status": "running"})
    with pytest.raises(ValueError, match="running jobs"):
        backup_project(store)
    store.put("jobs", "job_live", {"status": "completed"})
    (store.root / "artifacts/private").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="Symlinks"):
        backup_project(store)


def write_database_archive(path, data, schema_version=0):
    manifest = {
        "format": "research-project-v1",
        "schema_version": schema_version,
        "files": {
            "state.sqlite3": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        },
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("state.sqlite3", data)


def test_v02_restore_finishes_migrations_before_installation(tmp_path):
    store = Store(tmp_path / "old")
    store.put("sources", "paper_old", {"title": "Old stable ID"})
    store.db.execute("DROP TABLE schema_migrations")
    store.db.execute("PRAGMA user_version=0")
    store.db.commit()
    store.close()
    original = tmp_path / "old/.research/state.sqlite3"
    archive = tmp_path / "old.zip"
    write_database_archive(archive, original.read_bytes())
    original_digest = hashlib.sha256(original.read_bytes()).hexdigest()
    result = restore_project(archive, tmp_path / "restored-old")
    assert result["schema_version"] == SCHEMA_VERSION
    restored = Store(tmp_path / "restored-old")
    try:
        assert restored.get("sources", "paper_old") == {"title": "Old stable ID"}
        assert restored.db.execute("SELECT version FROM schema_migrations").fetchone()[0] == 1
    finally:
        restored.close()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_digest


@pytest.mark.parametrize(
    "change",
    [
        "wrong_migration_columns",
        "migration_conflict",
        "missing_columns",
        "view",
        "trigger",
        "expression",
    ],
)
def test_invalid_schema_or_migration_never_promotes_staging(tmp_path, change):
    store = Store(tmp_path / "source")
    if change == "wrong_migration_columns":
        store.db.execute("DROP TABLE schema_migrations")
        store.db.execute("CREATE TABLE schema_migrations(unrelated TEXT)")
        store.db.execute("PRAGMA user_version=0")
    elif change == "migration_conflict":
        store.db.execute("PRAGMA user_version=0")
    elif change == "missing_columns":
        store.db.execute("DROP TABLE notes")
        store.db.execute("CREATE TABLE notes(key TEXT,body TEXT)")
    elif change == "view":
        store.db.execute("CREATE VIEW malicious_view AS SELECT * FROM sources")
    elif change == "trigger":
        store.db.execute(
            "CREATE TRIGGER malicious_trigger AFTER INSERT ON sources BEGIN DELETE FROM sources; END"
        )
    else:
        store.db.execute("DROP TABLE notes")
        store.db.execute(
            "CREATE TABLE notes(key TEXT PRIMARY KEY,body TEXT,updated REAL,CHECK(length(body)>=0))"
        )
    store.db.commit()
    store.close()
    archive = tmp_path / "invalid-schema.zip"
    write_database_archive(archive, (tmp_path / "source/.research/state.sqlite3").read_bytes())
    destination = tmp_path / "destination"
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        restore_project(archive, destination)
    assert not (destination / ".research").exists()
    assert list(destination.glob(".research-import-*")) == []


def test_usage_ledger_symlinks_are_not_exported(store, tmp_path):
    (store.root / "usage.jsonl").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="Symlinks"):
        backup_project(store)


def test_unknown_detached_worker_blocks_backup_until_ownership_is_resolved(store):
    store.put("jobs", "job_unknown", {"status": "interrupted_unknown", "detached": True})
    with pytest.raises(ValueError, match="running jobs"):
        backup_project(store)
    store.put("jobs", "job_unknown", {"status": "interrupted_unknown", "detached": False})
    assert backup_project(store)["files"] >= 1
