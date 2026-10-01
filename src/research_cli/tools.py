from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from research_cli.config import Settings
from research_cli.storage import Store, encode
from research_cli.types import Approve

SKIP_DIRS = {
    ".git",
    ".pi",
    ".research",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Empty(Args):
    pass


class PathArgs(Args):
    path: str = "."


class ReadArgs(Args):
    path: str
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=150, ge=1, le=500)


class SearchArgs(Args):
    query: str = Field(min_length=1, max_length=1000)
    path: str = "."
    limit: int = Field(default=40, ge=1, le=100)


class EditArgs(Args):
    path: str
    old_text: str = Field(max_length=100000)
    new_text: str = Field(max_length=100000)
    expected_sha256: str = Field(description="SHA256 from read_file; use 'new' to create a file")


class ArtifactArgs(Args):
    artifact_id: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10000, ge=1, le=20000)


class NoteArgs(Args):
    key: str = Field(min_length=1, max_length=80)
    text: str = Field(max_length=2000)


class SkillArgs(Args):
    name: str


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable[[dict], Awaitable[object]]
    effect: str = "read"
    network: bool = False
    model: type[BaseModel] | None = None


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def path(self, value: str, write=False) -> Path:
        path = (self.root / value).resolve()
        for name in ["RESEARCH_CONFIG", "RESEARCH_MCP_CONFIG", "RESEARCH_MODEL_PROFILE"]:
            if os.environ.get(name) and path == Path(os.environ[name]).resolve():
                raise ValueError("Explicit configuration files are blocked")
        credentials = (
            Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
            / "research-cli"
            / "api.json"
        ).resolve()
        if path == credentials:
            raise ValueError("Saved API credentials are blocked")
        if not path.is_relative_to(self.root):
            raise ValueError("Path is outside the workspace")
        parts = path.relative_to(self.root).parts
        if any(
            p in SKIP_DIRS
            or p.startswith(".env")
            or p in {"research.toml", "id_rsa", "id_ed25519"}
            or p.endswith((".pem", ".key"))
            for p in parts
        ):
            raise ValueError(
                "Private state, configuration, credentials or ignored environment path"
            )
        if path.exists():
            if not (path.is_dir() or stat.S_ISREG(path.stat().st_mode)):
                raise ValueError("Only regular files and directories are supported")
            if write and path.is_file() and path.stat().st_nlink > 1:
                raise ValueError("Refusing to modify a hard-linked file")
        return path

    def files(self, value=".", limit=300):
        base = self.path(value)
        if base.is_file():
            return [base]
        if not base.is_dir():
            raise ValueError("Directory does not exist")
        results = []
        for root, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(files):
                if name.startswith("."):
                    continue
                try:
                    p = self.path(str(Path(root) / name))
                except ValueError:
                    continue
                results.append(p)
                if len(results) >= limit:
                    return results
        return results

    def read(self, path):
        p = self.path(path)
        if not p.is_file() or p.stat().st_size > 2_000_000:
            raise ValueError("Expected a text file no larger than 2 MB")
        data = p.read_bytes()
        if b"\0" in data:
            raise ValueError("Binary file; use an appropriate document tool")
        return p, data.decode("utf-8"), hashlib.sha256(data).hexdigest()


class Registry:
    def __init__(self, store: Store, settings: Settings):
        self.store, self.settings = store, settings
        self.tools: dict[str, Tool] = {}

    def add(self, name, description, model, handler, effect="read", network=False):
        if name in self.tools:
            raise ValueError(f"Duplicate tool: {name}")
        self.tools[name] = Tool(
            name, description, model.model_json_schema(), handler, effect, network, model
        )

    def schemas(self):
        return [
            {"name": t.name, "description": t.description, "parameters": t.schema}
            for t in self.tools.values()
        ]

    async def invoke(self, name: str, arguments: str, approve: Approve):
        tool = self.tools.get(name)
        if tool is None:
            return {"ok": False, "error": "unknown_tool", "detail": name}
        try:
            if len(arguments) > 250000:
                raise ValueError("Arguments exceed size limit")
            args = json.loads(arguments)
            Draft202012Validator(tool.schema).validate(args)
            if tool.model:
                args = tool.model.model_validate(args, strict=True).model_dump()
        except Exception as exc:
            # Validation failures are observations the model may correct, not process crashes.
            return {"ok": False, "error": "invalid_arguments", "detail": str(exc)[:1200]}
        if tool.network and not self.settings.allow_network:
            return {"ok": False, "error": "network_disabled"}
        if tool.effect != "read":
            if self.settings.permission == "read-only":
                return {"ok": False, "error": "permission_denied", "detail": "read-only mode"}
            auto = self.settings.permission == "workspace-write" and tool.effect == "write"
            if not auto and not await approve(name, args):
                return {"ok": False, "error": "permission_denied", "detail": "not approved"}
        try:
            output = await asyncio.wait_for(tool.handler(args), self.settings.tool_timeout)
            text = encode(output)
            if len(text) > self.settings.tool_result_chars:
                output = {
                    **self.store.artifact(text),
                    "truncated": True,
                    "preview": text[: self.settings.tool_result_chars],
                }
            return {"ok": True, "result": output}
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            return {"ok": False, "error": "timeout", "detail": "Check side effects before retrying"}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:1500]}


BUILTIN_SKILLS = {
    "paper-code-review": (
        "Compare a paper's claims against its implementation.",
        "Read the actual paper passages and record their source positions. Locate the repository "
        "association evidence, pin the commit, inspect configuration and evaluation code. Separate "
        "author-provided code from third-party replication. Compare equations, preprocessing, splits, "
        "loss, metrics and defaults. Missing information is a gap, not permission to invent it.",
    ),
    "reproduction": (
        "Plan and validate a bounded reproduction experiment.",
        "Inspect available code, dependencies, data licenses and resource requirements. Establish "
        "a baseline and fixed dataset split. Record seeds, code revision, environment, metrics and "
        "tolerance before running. Distinguish environment setup, smoke run, result reproduction "
        "and full paper replication. Keep negative results. Use the user's actual compute limits.",
    ),
    "research-critique": (
        "Find testable limitations with supporting and opposing evidence.",
        "Identify assumptions and their scope. Search for counterexamples and alternative explanations. "
        "Cite evidence for each proposed limitation. Novelty is a claim to investigate. Propose "
        "falsifiable predictions and controlled comparisons; do not infer novelty from an empty search.",
    ),
}


def skill_catalog():
    return "\n".join(f"{name}: {desc}" for name, (desc, _) in BUILTIN_SKILLS.items())


def register_files(registry: Registry):
    ws, store = Workspace(registry.store.workspace), registry.store

    async def listing(a):
        paths = ws.files(a["path"], 300)
        return {
            "files": [str(p.relative_to(ws.root)) for p in paths],
            "limit": 300,
            "possibly_truncated": len(paths) == 300,
        }

    async def read(a):
        p, content, digest = ws.read(a["path"])
        lines = content.splitlines()
        start = a["start_line"] - 1
        return {
            "path": str(p.relative_to(ws.root)),
            "sha256": digest,
            "total_lines": len(lines),
            "text": "\n".join(
                f"{i + 1}: {lines[i]}"
                for i in range(start, min(len(lines), start + a["max_lines"]))
            ),
        }

    async def search(a):
        found = []
        paths = ws.files(a["path"], 2000)
        for p in paths:
            try:
                _, text, _ = ws.read(str(p))
            except (ValueError, UnicodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if a["query"].casefold() in line.casefold():
                    found.append(
                        {"path": str(p.relative_to(ws.root)), "line": number, "text": line[:500]}
                    )
                    if len(found) >= a["limit"]:
                        return {"matches": found, "truncated": True}
            await asyncio.sleep(0)
        return {"matches": found, "truncated": len(paths) == 2000}

    async def edit(a):
        path = ws.path(a["path"], write=True)
        if a["expected_sha256"] == "new":
            if path.exists() or a["old_text"]:
                raise ValueError("New files require a missing path and empty old_text")
            before, after = "", a["new_text"]
        else:
            _, before, digest = ws.read(a["path"])
            if digest != a["expected_sha256"]:
                raise ValueError("File changed since reading; inspect it again")
            if not a["old_text"] or before.count(a["old_text"]) != 1:
                raise ValueError("old_text must match exactly once")
            after = before.replace(a["old_text"], a["new_text"], 1)
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(True),
                after.splitlines(True),
                fromfile=a["path"],
                tofile=a["path"],
            )
        )
        backup = store.artifact(before)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Revalidate path after making parents; no arbitrary shell patch command.
        path = ws.path(a["path"], write=True)
        if a["expected_sha256"] == "new":
            with path.open("x", encoding="utf-8") as f:
                f.write(after)
        else:
            if hashlib.sha256(path.read_bytes()).hexdigest() != a["expected_sha256"]:
                raise ValueError("Concurrent modification detected")
            path.write_text(after, encoding="utf-8")
        return {
            "path": a["path"],
            "sha256": hashlib.sha256(after.encode()).hexdigest(),
            "diff": diff,
            "before": backup,
        }

    async def git_diff(a):
        proc = await asyncio.create_subprocess_exec(
            "git",
            "--no-pager",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            cwd=ws.root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), 10)
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        return {
            "exit_code": proc.returncode,
            "diff": out.decode(errors="replace"),
            "stderr": err.decode(errors="replace"),
        }

    async def artifact(a):
        return store.read_artifact(a["artifact_id"], a["offset"], a["limit"])

    async def note(a):
        if a["key"] not in store.notes() and len(store.notes()) >= 20:
            raise ValueError("Project note limit reached; update an existing note")
        store.note(a["key"], a["text"])
        return {"saved": a["key"]}

    async def skill(a):
        if a["name"] not in BUILTIN_SKILLS:
            raise ValueError("Unknown skill")
        desc, body = BUILTIN_SKILLS[a["name"]]
        return {"name": a["name"], "description": desc, "instructions": body}

    registry.add(
        "list_files",
        "List accessible workspace files (bounded; excludes private state).",
        PathArgs,
        listing,
    )
    registry.add(
        "read_file", "Read a UTF-8 text file with line numbers and content hash.", ReadArgs, read
    )
    registry.add(
        "search_code",
        "Literal search in workspace text files; returns paths and line numbers.",
        SearchArgs,
        search,
    )
    registry.add(
        "edit_file",
        "Create or replace one exact text occurrence; requires read_file hash. Returns diff and backup.",
        EditArgs,
        edit,
        "write",
    )
    registry.add(
        "git_diff",
        "Inspect uncommitted tracked-file changes; does not include untracked files.",
        Empty,
        git_diff,
    )
    registry.add(
        "read_artifact",
        "Read a slice of an archived full tool result or transcript by ID.",
        ArtifactArgs,
        artifact,
    )
    registry.add(
        "remember",
        "Save a project note for future turns. Preserve evidence IDs and uncertainty.",
        NoteArgs,
        note,
        "write",
    )
    registry.add(
        "load_skill", "Load one research method on demand from the skill catalog.", SkillArgs, skill
    )
