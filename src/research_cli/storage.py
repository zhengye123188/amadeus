from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1


def identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class Store:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".research"
        if self.root.is_symlink():
            raise ValueError(".research may not be a symlink")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ["artifacts", "jobs"]:
            target = self.root / name
            if target.is_symlink():
                raise ValueError(f"{target} may not be a symlink")
            target.mkdir(exist_ok=True)
        db = self.root / "state.sqlite3"
        if db.is_symlink():
            raise ValueError("State database may not be a symlink")
        self.db = sqlite3.connect(db)
        self.db.row_factory = sqlite3.Row
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self.db.close()
            raise ValueError("Project database was created by a newer Research CLI; upgrade first")
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL,
                summary TEXT DEFAULT '', cutoff INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT, turn TEXT,
                body TEXT, FOREIGN KEY(session) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT, turn TEXT,
                created REAL, body TEXT
            );
            CREATE TABLE IF NOT EXISTS notes (
                key TEXT PRIMARY KEY, body TEXT, updated REAL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY, path TEXT, sha256 TEXT, size INTEGER, created REAL
            );
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, body TEXT, created REAL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY, source TEXT, position TEXT, text TEXT,
                vector TEXT, embedding_model TEXT
            );
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY, body TEXT, created REAL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, body TEXT, updated REAL
            );
        """)
        # Version zero is the v0.2 database. Preserve IDs, JSON bodies and history.
        # Future migrations must advance one version at a time in a transaction.
        if version < 1:
            with self.db:
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations "
                    "(version INTEGER PRIMARY KEY, applied REAL NOT NULL)"
                )
                self.db.execute("INSERT INTO schema_migrations VALUES(1,?)", (time.time(),))
                self.db.execute("PRAGMA user_version=1")

    def database_info(self):
        return {
            "schema_version": self.db.execute("PRAGMA user_version").fetchone()[0],
            "supported_schema_version": SCHEMA_VERSION,
            "integrity": self.db.execute("PRAGMA quick_check").fetchone()[0],
        }

    def close(self):
        self.db.close()

    @contextmanager
    def lock(self):
        """One CLI owner per workspace; lock is released by the OS after a crash."""
        import fcntl

        path = self.root / "instance.lock"
        if path.is_symlink():
            raise ValueError("Lock file may not be a symlink")
        with path.open("a+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("Another research process owns this workspace") from exc
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def create_session(self, title="Untitled") -> str:
        sid = identifier("s")
        now = time.time()
        self.db.execute(
            "INSERT INTO sessions(id,title,created,updated) VALUES(?,?,?,?)",
            (sid, title[:100], now, now),
        )
        self.db.commit()
        return sid

    def session(self, sid):
        row = self.db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            raise ValueError(f"Unknown session: {sid}")
        return dict(row)

    def sessions(self):
        return [
            dict(r)
            for r in self.db.execute("SELECT id,title,updated FROM sessions ORDER BY updated DESC")
        ]

    def message(self, sid, turn, body):
        with self.db:
            self.db.execute(
                "INSERT INTO messages(session,turn,body) VALUES(?,?,?)", (sid, turn, encode(body))
            )
            self.db.execute("UPDATE sessions SET updated=? WHERE id=?", (time.time(), sid))

    def messages(self, sid, after=0):
        return [
            {"id": r["id"], "turn": r["turn"], **json.loads(r["body"])}
            for r in self.db.execute(
                "SELECT * FROM messages WHERE session=? AND id>? ORDER BY id", (sid, after)
            )
        ]

    def event(self, sid, turn, body):
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO events(session,turn,created,body) VALUES(?,?,?,?)",
            (sid, turn, now, encode(body)),
        )
        self.db.commit()
        return {"event_id": cur.lastrowid, "session_id": sid, "turn_id": turn, "time": now, **body}

    def events(self, sid, limit=200):
        rows = self.db.execute(
            "SELECT * FROM events WHERE session=? ORDER BY id DESC LIMIT ?", (sid, limit)
        ).fetchall()
        return [
            {
                "event_id": r["id"],
                "turn_id": r["turn"],
                "time": r["created"],
                **json.loads(r["body"]),
            }
            for r in reversed(rows)
        ]

    def put(self, table: str, key: str, body: dict):
        if table not in {"sources", "evidence", "jobs"}:
            raise ValueError("Unsupported record table")
        stamp = "updated" if table == "jobs" else "created"
        with self.db:
            self.db.execute(
                f"INSERT OR REPLACE INTO {table}(id,body,{stamp}) VALUES(?,?,?)",
                (key, encode(body), time.time()),
            )

    def get(self, table, key):
        if table not in {"sources", "evidence", "jobs"}:
            raise ValueError("Unsupported record table")
        row = self.db.execute(f"SELECT body FROM {table} WHERE id=?", (key,)).fetchone()
        if not row:
            raise ValueError(f"Unknown {table} record: {key}")
        return json.loads(row[0])

    def records(self, table):
        if table not in {"sources", "evidence", "jobs"}:
            raise ValueError("Unsupported record table")
        return [json.loads(r[0]) for r in self.db.execute(f"SELECT body FROM {table}")]

    def note(self, key, body):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?)", (key, body, time.time()))

    def notes(self):
        return {r[0]: r[1] for r in self.db.execute("SELECT key,body FROM notes ORDER BY key")}

    def artifact(self, content: str) -> dict:
        data = content.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        aid = "a_" + digest[:24]
        path = self.root / "artifacts" / (aid + ".txt")
        if path.is_symlink():
            raise ValueError("Artifact path is a symlink")
        path.write_bytes(data)
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)",
                (aid, str(path.relative_to(self.root)), digest, len(data), time.time()),
            )
        return {"artifact_id": aid, "sha256": digest, "bytes": len(data)}

    def read_artifact(self, aid: str, offset=0, limit=10000):
        row = self.db.execute("SELECT path FROM artifacts WHERE id=?", (aid,)).fetchone()
        if not row:
            raise ValueError("Unknown artifact")
        path = (self.root / row[0]).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Artifact escaped storage")
        text = path.read_text()
        return {"artifact_id": aid, "text": text[offset : offset + limit], "total_chars": len(text)}

    def recover(self, sid):
        """Complete interrupted protocol pairs without re-executing any tool."""
        pending = {}
        for msg in self.messages(sid):
            if msg["role"] == "assistant":
                for call in msg.get("calls", []):
                    pending[call["id"]] = (call, msg["turn"])
            elif msg["role"] == "tool":
                pending.pop(msg["call_id"], None)
        for call, turn in pending.values():
            self.message(
                sid,
                turn,
                {
                    "role": "tool",
                    "call_id": call["id"],
                    "name": call["name"],
                    "content": encode(
                        {
                            "ok": False,
                            "error": "interrupted",
                            "detail": "Outcome may be unknown. Inspect state before retrying; not replayed.",
                        }
                    ),
                },
            )
        return len(pending)
