"""Install the built wheel as a real CLI without altering the user's tool directory."""

from __future__ import annotations

import argparse
import email
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(p for p in archive.namelist() if p.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(archive.read(metadata_path))
        if metadata["Name"] != "research-terminal":
            raise SystemExit("Unexpected wheel project name")
        expected_version = metadata["Version"]

    with tempfile.TemporaryDirectory(prefix="research-tool-smoke-") as folder:
        root = Path(folder)
        env = {
            **os.environ,
            "UV_TOOL_DIR": str(root / "tools"),
            "UV_TOOL_BIN_DIR": str(root / "bin"),
        }
        subprocess.run(
            ["uv", "tool", "install", "--python", sys.executable, str(wheel) + "[mcp]"],
            check=True,
            env=env,
            timeout=180,
        )
        executable = root / "bin" / "research-legacy"
        result = subprocess.run(
            [str(executable), "--version"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.stdout.strip() != expected_version:
            raise SystemExit("Installed command version does not match the wheel")
        backend = subprocess.run(
            [str(root / "bin" / "research-mcp"), "--version"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=root,
        )
        if backend.stdout.strip() != expected_version:
            raise SystemExit("Installed MCP backend version mismatch")
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "fixture.txt").write_text("installed wheel can read workspace files")
        result = subprocess.run(
            [
                str(executable),
                "--demo",
                "--workspace",
                str(workspace),
                "exec",
                "read @fixture.txt",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=root,
            timeout=30,
        )
        events = [json.loads(line) for line in result.stdout.splitlines()]
        if events[-1]["status"] != "completed":
            raise SystemExit("Installed CLI did not complete the demo turn")
        tool = next(e for e in events if e["type"] == "tool_finished")
        if "installed wheel can read workspace files" not in tool["result"]["result"]["text"]:
            raise SystemExit("Installed CLI did not return the expected file content")
        print(
            f"PASS: isolated wheel, research-mcp/research-legacy {expected_version}, and dynamic file tool"
        )


if __name__ == "__main__":
    main()
