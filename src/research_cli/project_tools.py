"""Project navigation and explicit, conflict-checked code checkpoints."""

from __future__ import annotations

import ast
import asyncio
import base64
import difflib
import fnmatch
import hashlib
import json
import shutil
import time

from pydantic import Field

from research_cli.storage import encode, identifier
from research_cli.tools import Args, Workspace


class SearchProject(Args):
    query: str = Field(min_length=1, max_length=500)
    path: str = "."
    globs: list[str] = Field(default_factory=list, max_length=20)
    regex: bool = False
    case_sensitive: bool = False
    limit: int = Field(default=40, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class Symbols(Args):
    path: str


class CheckpointCreate(Args):
    paths: list[str] = Field(min_length=1, max_length=100)
    label: str = Field(default="Before code change", max_length=200)


class CheckpointID(Args):
    checkpoint_id: str


class CheckpointRestore(CheckpointID):
    expected_current_sha256: dict[str, str] = Field(
        description="Exact paths and current hashes from inspect_checkpoint; use 'missing' for absent files."
    )


class ProjectTools:
    def __init__(self, registry):
        self.registry, self.store = registry, registry.store
        self.ws = Workspace(self.store.workspace)
        self.store.db.execute(
            "CREATE TABLE IF NOT EXISTS code_checkpoints (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
        )
        self.store.db.commit()

    async def search(self, a):
        paths = self.ws.files(a["path"], 3000)
        readable = []
        for path in paths:
            relative = path.relative_to(self.ws.root).as_posix()
            if a["globs"] and not any(fnmatch.fnmatchcase(relative, glob) for glob in a["globs"]):
                continue
            try:
                _, text, _ = self.ws.read(str(path))
            except (ValueError, UnicodeError, OSError):
                continue
            readable.append((path, text))
        found = []
        truncated = len(paths) == 3000
        if a["regex"]:
            executable = shutil.which("rg")
            if not executable:
                raise ValueError("Regex search needs ripgrep (rg); literal search works without it")
            if readable:
                argv = [
                    executable,
                    "--no-config",
                    "--json",
                    "--max-count=100",
                    "--max-columns=1000",
                    "--max-columns-preview",
                    "--regexp",
                    a["query"],
                ]
                if not a["case_sensitive"]:
                    argv.append("--ignore-case")
                argv.extend(["--", *(str(path) for path, _ in readable)])
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=self.ws.root,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    output = bytearray()

                    async def consume():
                        while block := await proc.stdout.read(4096):
                            output.extend(block)
                            if len(output) > 2_000_000:
                                raise ValueError(
                                    "Search output exceeds 2 MB; narrow the query or globs"
                                )
                        error = await proc.stderr.read(4000)
                        await proc.wait()
                        return error

                    error = await asyncio.wait_for(consume(), 10)
                    if proc.returncode not in {0, 1}:
                        raise ValueError(
                            "Invalid search expression: " + error.decode(errors="replace")[:500]
                        )
                    for line in output.splitlines():
                        event = json.loads(line)
                        if event["type"] == "match":
                            data = event["data"]
                            found.append(
                                {
                                    "path": str(
                                        self.ws.path(data["path"]["text"]).relative_to(self.ws.root)
                                    ),
                                    "line": data["line_number"],
                                    "text": data["lines"]["text"].rstrip()[:1000],
                                }
                            )
                finally:
                    if proc.returncode is None:
                        proc.kill()
                        await proc.wait()
        else:
            needle = a["query"] if a["case_sensitive"] else a["query"].casefold()
            for path, text in readable:
                for number, line in enumerate(text.splitlines(), 1):
                    value = line if a["case_sensitive"] else line.casefold()
                    if needle in value:
                        found.append(
                            {
                                "path": str(path.relative_to(self.ws.root)),
                                "line": number,
                                "text": line[:1000],
                            }
                        )
                        if len(found) >= a["offset"] + a["limit"] + 1:
                            break
                if len(found) >= a["offset"] + a["limit"] + 1:
                    truncated = True
                    break
                await asyncio.sleep(0)
        end = a["offset"] + a["limit"]
        return {
            "matches": found[a["offset"] : end],
            "offset": a["offset"],
            "next_offset": end if len(found) > end else None,
            "truncated": truncated or len(found) > end,
            "file_scan_limit": 3000,
            "backend": "ripgrep" if a["regex"] else "literal",
        }

    async def symbols(self, a):
        path, text, digest = self.ws.read(a["path"])
        if path.suffix != ".py":
            return {
                "supported": False,
                "reason": "Structural symbol inspection currently supports Python files",
            }
        tree = ast.parse(text, filename=str(path))
        result = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                result.append(
                    {
                        "name": node.name,
                        "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                        "line": node.lineno,
                        "end_line": node.end_lineno,
                    }
                )
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                result.append(
                    {
                        "kind": "import",
                        "line": node.lineno,
                        "module": getattr(node, "module", None),
                        "names": [alias.name for alias in node.names],
                    }
                )
        result.sort(key=lambda value: value["line"])
        return {
            "supported": True,
            "path": str(path.relative_to(self.ws.root)),
            "sha256": digest,
            "symbols": result[:500],
            "truncated": len(result) > 500,
        }

    def state(self, value):
        path = self.ws.path(value, write=True)
        if not path.exists():
            return "missing", None
        _, text, digest = self.ws.read(value)
        return digest, text

    async def create(self, a):
        files = {}
        total = 0
        for value in a["paths"]:
            path = str(self.ws.path(value, write=True).relative_to(self.ws.root))
            if path in files:
                raise ValueError("Checkpoint paths must be unique")
            digest, text = self.state(path)
            data = text.encode("utf-8") if text is not None else b""
            total += len(data)
            if total > 10_000_000:
                raise ValueError("Checkpoint exceeds 10 MB; select fewer files")
            files[path] = {
                "sha256": digest,
                "content": base64.b64encode(data).decode() if text is not None else None,
            }
        checkpoint = {
            "checkpoint_id": identifier("checkpoint"),
            "label": a["label"],
            "created": time.time(),
            "files": files,
        }
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO code_checkpoints VALUES(?,?)",
                (checkpoint["checkpoint_id"], encode(checkpoint)),
            )
        return {
            **{key: checkpoint[key] for key in ("checkpoint_id", "label", "created")},
            "files": {path: value["sha256"] for path, value in files.items()},
            "scope": "Only explicitly selected UTF-8 files; not a Git commit or full project backup",
        }

    def get(self, identifier_value):
        row = self.store.db.execute(
            "SELECT body FROM code_checkpoints WHERE id=?", (identifier_value,)
        ).fetchone()
        if not row:
            raise ValueError("Unknown checkpoint")
        return json.loads(row[0])

    async def inspect(self, a):
        checkpoint = self.get(a["checkpoint_id"])
        files = {}
        for path, original in checkpoint["files"].items():
            digest, text = self.state(path)
            before = (
                base64.b64decode(original["content"]).decode("utf-8")
                if original["content"] is not None
                else ""
            )
            diff = "".join(
                difflib.unified_diff(
                    before.splitlines(True),
                    (text or "").splitlines(True),
                    fromfile="checkpoint/" + path,
                    tofile="current/" + path,
                )
            )
            files[path] = {
                "checkpoint_sha256": original["sha256"],
                "current_sha256": digest,
                "diff": diff[:20000],
                "diff_truncated": len(diff) > 20000,
            }
        return {
            "checkpoint_id": a["checkpoint_id"],
            "label": checkpoint["label"],
            "files": files,
            "expected_current_sha256": {
                path: value["current_sha256"] for path, value in files.items()
            },
        }

    async def restore(self, a):
        checkpoint = self.get(a["checkpoint_id"])
        if set(a["expected_current_sha256"]) != set(checkpoint["files"]):
            raise ValueError("Provide exact current hashes for every checkpoint file")
        decoded = {}
        for value, original in checkpoint["files"].items():
            self.ws.path(value, write=True)
            if original["content"] is None:
                if original["sha256"] != "missing":
                    raise ValueError("Checkpoint content checksum mismatch")
                decoded[value] = None
            else:
                data = base64.b64decode(original["content"], validate=True)
                if hashlib.sha256(data).hexdigest() != original["sha256"]:
                    raise ValueError("Checkpoint content checksum mismatch")
                decoded[value] = data
        # Validate all files before touching any of them; never use stale baseline hashes.
        for path in checkpoint["files"]:
            if self.state(path)[0] != a["expected_current_sha256"][path]:
                raise ValueError(
                    "File changed since checkpoint inspection; inspect again before restoring"
                )
        for value, original in checkpoint["files"].items():
            path = self.ws.path(value, write=True)
            if self.state(value)[0] != a["expected_current_sha256"][value]:
                raise ValueError(
                    "Concurrent modification during restore; completed files remain restored"
                )
            if decoded[value] is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path = self.ws.path(value, write=True)
                path.write_bytes(decoded[value])
        self.store.event(
            "mcp",
            "restore_checkpoint",
            {
                "type": "checkpoint_restore",
                "checkpoint_id": a["checkpoint_id"],
                "paths": list(checkpoint["files"]),
            },
        )
        return {
            "checkpoint_id": a["checkpoint_id"],
            "restored": {
                path: original["sha256"] for path, original in checkpoint["files"].items()
            },
        }

    def register(self):
        r = self.registry
        r.add(
            "search_project",
            "Search validated project text with globs and pagination. Regex requires ripgrep; private paths are excluded.",
            SearchProject,
            self.search,
        )
        r.add(
            "inspect_symbols",
            "Inspect Python imports/classes/functions and source lines without executing code.",
            Symbols,
            self.symbols,
        )
        r.add(
            "create_checkpoint",
            "Save selected UTF-8 project files before editing, including absent paths for planned new files.",
            CheckpointCreate,
            self.create,
            "write",
        )
        r.add(
            "inspect_checkpoint",
            "Compare selected checkpoint files with current contents and return hashes needed for a conflict-checked restore.",
            CheckpointID,
            self.inspect,
        )
        r.add(
            "restore_checkpoint",
            "Restore selected checkpoint files only if exact current hashes still match. May delete files that were originally absent.",
            CheckpointRestore,
            self.restore,
            "write",
        )
