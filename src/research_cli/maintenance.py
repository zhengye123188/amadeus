"""Explicit project maintenance commands; restore never overwrites an existing project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

from research_cli import __version__
from research_cli.storage import SCHEMA_VERSION, Store, encode
from research_cli.tools import Empty

MAX_ARCHIVE_BYTES = 512_000_000


def backup_project(store: Store, output: Path | None = None):
    active = [j for j in store.records("jobs") if j["status"] in {"starting", "running"}]
    if active:
        raise ValueError("Wait for or cancel running jobs before backing up project files")
    directory = store.root / "backups"
    if directory.is_symlink():
        raise ValueError("Backup directory may not be a symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    destination = output or directory / f"project-{time.time_ns()}.zip"
    if destination.exists() or destination.is_symlink():
        raise ValueError("Backup destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        database = Path(temporary) / "state.sqlite3"
        target = sqlite3.connect(database)
        try:
            store.db.backup(target)  # Includes committed WAL data consistently.
        finally:
            target.close()
        files = {"state.sqlite3": database}
        for folder in ("artifacts", "jobs"):
            for path in sorted((store.root / folder).rglob("*")):
                if path.is_symlink():
                    raise ValueError("Symlinks cannot be included in a project archive")
                if path.is_file():
                    if not stat.S_ISREG(path.stat().st_mode):
                        raise ValueError("Archive contains a nonregular file")
                    files[path.relative_to(store.root).as_posix()] = path
        if sum(p.stat().st_size for p in files.values()) > MAX_ARCHIVE_BYTES:
            raise ValueError("Project archive exceeds 512 MB; export large datasets separately")
        manifest = {
            "format": "research-project-v1",
            "cli_version": __version__,
            "schema_version": SCHEMA_VERSION,
            "created": time.time(),
            "files": {},
            "notice": "Contains project evidence and code snapshots. API settings and Pi transcripts are not included.",
        }
        try:
            with destination.open("xb") as handle:
                os.chmod(destination, 0o600)
                with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive:
                    for name, path in files.items():
                        data = path.read_bytes()
                        manifest["files"][name] = {
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "bytes": len(data),
                        }
                        archive.writestr(name, data)
                    archive.writestr("manifest.json", encode(manifest))
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    return {
        "path": str(destination),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "files": len(files),
        "schema_version": SCHEMA_VERSION,
    }


def restore_project(archive_path: Path, workspace: Path):
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    destination = workspace / ".research"
    if destination.exists() or destination.is_symlink():
        raise ValueError(
            "Restore requires a workspace without .research; existing data is never overwritten"
        )
    if not archive_path.is_file() or archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Expected a project archive no larger than 512 MB")
    temporary = Path(tempfile.mkdtemp(prefix=".research-import-", dir=workspace))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or len(names) > 20000:
                raise ValueError("Duplicate archive members or excessive file count")
            if sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES:
                raise ValueError("Expanded archive exceeds 512 MB")
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in entry.filename
                    or entry.filename != path.as_posix()
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or not (
                        entry.filename in {"manifest.json", "state.sqlite3"}
                        or path.parts[0] in {"artifacts", "jobs"}
                    )
                ):
                    raise ValueError("Unsafe project archive member")
            manifest_data = archive.read("manifest.json")
            if len(manifest_data) > 5_000_000:
                raise ValueError("Manifest is too large")
            manifest = json.loads(manifest_data)
            if manifest["format"] != "research-project-v1":
                raise ValueError("Unknown archive format")
            if manifest["schema_version"] > SCHEMA_VERSION:
                raise ValueError("Archive needs a newer Research CLI")
            if set(names) - {"manifest.json"} != set(manifest["files"]):
                raise ValueError("Archive file list differs from manifest")
            for name, expected in manifest["files"].items():
                data = archive.read(name)
                if (
                    len(data) != expected["bytes"]
                    or hashlib.sha256(data).hexdigest() != expected["sha256"]
                ):
                    raise ValueError("Archive checksum mismatch")
                path = temporary / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                path.chmod(0o600)
        database = sqlite3.connect(temporary / "state.sqlite3")
        try:
            if database.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Invalid project database")
            if database.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
                raise ValueError("Database needs a newer Research CLI")
        finally:
            database.close()
        # The staging directory is fully verified before becoming the project state.
        if destination.exists():
            raise ValueError("Project state appeared during restore; retry in an empty workspace")
        temporary.rename(destination)
        restored = Store(workspace)
        try:
            result = restored.database_info()
        finally:
            restored.close()
        return {"workspace": str(workspace), "restored_files": len(manifest["files"]), **result}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def register_maintenance(registry):
    async def backup(_args):
        return backup_project(registry.store)

    async def info(_args):
        return registry.store.database_info()

    registry.add(
        "backup_project",
        "Create a checksummed project archive of database, evidence and job files. Wait for running jobs first. Does not include API settings or Pi transcripts.",
        Empty,
        backup,
        "write",
    )
    registry.add("project_data_info", "Inspect project database schema and integrity.", Empty, info)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "restore", "info"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", type=Path, required=True)
        if name == "backup":
            command.add_argument("--output", type=Path)
        if name == "restore":
            command.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "restore":
            output = restore_project(args.archive, args.workspace)
        else:
            store = Store(args.workspace)
            try:
                with store.lock():
                    output = (
                        backup_project(store, args.output)
                        if args.command == "backup"
                        else store.database_info()
                    )
            finally:
                store.close()
        print(encode(output))
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, sqlite3.DatabaseError) as exc:
        parser.exit(1, f"Project maintenance failed: {exc}\n")


if __name__ == "__main__":
    main()
