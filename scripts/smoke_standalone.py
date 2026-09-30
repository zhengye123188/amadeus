"""Install a real self-extractor without developer runtimes on PATH, then exercise Pi/MCP."""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pexpect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    args = parser.parse_args()
    installer = args.installer.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="research-standalone-smoke-") as temporary:
        root = Path(temporary).resolve()
        prefix, commands, workspace = root / "Installed App 空格", root / "commands", root / "work"
        workspace.mkdir()
        (workspace / "README.md").write_text("Standalone fixture: evidence, memory, experiments.")
        poison = root / "no-developer-tools"
        poison.mkdir()
        for name in ("node", "npm", "npx", "uv", "python", "python3"):
            path = poison / name
            path.write_text(
                "#!/bin/sh\necho 'External developer runtime was invoked' >&2\nexit 97\n"
            )
            path.chmod(0o755)
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("RESEARCH_", "OPENAI_", "ANTHROPIC_", "PI_", "PYTHON"))
        }
        env.update(
            {
                "PATH": str(poison) + ":/usr/bin:/bin",
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "PI_CODING_AGENT_DIR": str(root / "agent"),
                "PI_OFFLINE": "1",
                "PI_TELEMETRY": "0",
                "TERM": "xterm-256color",
            }
        )

        def run(*command, success=True):
            result = subprocess.run(
                command, cwd=workspace, env=env, capture_output=True, text=True, timeout=180
            )
            if success and result.returncode:
                raise AssertionError(result.stderr + result.stdout)
            if not success:
                assert result.returncode != 0, "Expected installation rejection"
            return result

        install_args = ("--prefix", str(prefix), "--bin-dir", str(commands))
        run("/bin/sh", str(installer), *install_args)
        research = str(commands / "research")
        doctor = json.loads(run(research, "doctor").stdout)
        assert doctor["standalone"] and doctor["node"] == "22.23.1"
        assert doctor["backend"] == doctor["version"]
        assert Path(doctor["python"]).is_relative_to(prefix)
        assert "already includes" in run(research, "setup").stdout
        python_env = {**env, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
        subprocess.run(
            [
                doctor["python"],
                "-I",
                "-B",
                "-c",
                "import ssl, sqlite3, mcp, pydantic_core; print('Bundled Python native imports OK')",
            ],
            env=python_env,
            check=True,
        )

        fixture_key = "standalone-fixture-not-a-real-key"
        requests, failures = [], []

        class Endpoint(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                if self.headers.get("Authorization") != f"Bearer {fixture_key}":
                    failures.append("authorization")
                    self.send_response(401)
                    self.end_headers()
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(body)
                number = len(requests)
                if number < 3:
                    name = "read" if number == 1 else "mcp__research__project_status"
                    arguments = {"path": "README.md"} if number == 1 else {}
                    delta = {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": f"call_{number}",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(arguments)},
                            }
                        ],
                    }
                else:
                    delta = {"role": "assistant", "content": "Standalone tool loop completed."}
                chunk = {
                    "id": f"test-{number}",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                chunk["choices"][0].update(
                    delta={}, finish_reason="tool_calls" if number < 3 else "stop"
                )
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            child = pexpect.spawn(
                research, ["configure"], cwd=str(workspace), env=env, encoding="utf8", timeout=30
            )
            try:
                child.expect_exact("API base URL")
                child.sendline(f"http://127.0.0.1:{server.server_port}/v1")
                child.expect_exact("Model ID")
                child.sendline("fixture")
                child.expect_exact("Protocol")
                child.sendline("chat")
                child.expect_exact("API Key (hidden")
                child.sendline(fixture_key)
                child.expect(pexpect.EOF)
                assert fixture_key not in child.before, "Secret echoed during configuration"
            finally:
                child.close(force=True)
            assert child.exitstatus == 0
            saved = root / "config/research-cli/api.json"
            assert saved.stat().st_mode & 0o777 == 0o600
            saved_bytes = saved.read_bytes()

            # A fresh process has no API env variables; it must use persistent settings.
            app = subprocess.Popen(
                [research, "--mode", "rpc", "--workspace", str(workspace), "--offline"],
                cwd=workspace,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            events, mailbox = [], queue.Queue()

            def read_events():
                for line in app.stdout:
                    mailbox.put(line)
                mailbox.put(None)

            reader = threading.Thread(target=read_events, daemon=True)
            reader.start()
            try:
                app.stdin.write(
                    json.dumps(
                        {
                            "id": "smoke",
                            "type": "prompt",
                            "message": "Read README.md and inspect project status.",
                        }
                    )
                    + "\n"
                )
                app.stdin.flush()
                while True:
                    line = mailbox.get(timeout=45)
                    assert line is not None, "Pi exited before completing the request"
                    event = json.loads(line)
                    events.append(event)
                    if event.get("type") == "agent_settled":
                        break
                tools = [e for e in events if e.get("type") == "tool_execution_end"]
                assert len(tools) == 2 and all(not e.get("isError") for e in tools), events
                assert len(requests) == 3 and not failures
                assert "Standalone fixture" in json.dumps(requests[-1])
                assert fixture_key not in json.dumps(events)
                app.stdin.close()
                app.wait(timeout=15)
                assert app.returncode == 0, app.stderr.read()
            finally:
                if app.poll() is None:
                    app.kill()
                    app.wait()
        finally:
            server.shutdown()
            server.server_close()

        terminal = pexpect.spawn(
            research,
            ["--workspace", str(workspace), "--offline"],
            cwd=str(workspace),
            env=env,
            encoding="utf8",
            timeout=30,
            dimensions=(35, 120),
        )
        try:
            terminal.expect_exact("research ·")
            terminal.send("/research-status\r")
            terminal.expect_exact("sources")
            terminal.sendcontrol("d")
            terminal.expect(pexpect.EOF)
        finally:
            terminal.close(force=True)
        assert terminal.exitstatus == 0, "Interactive terminal did not exit cleanly"

        active = os.readlink(prefix / "current")
        run("/bin/sh", str(installer), *install_args)
        assert os.readlink(prefix / "current") == active
        assert saved.read_bytes() == saved_bytes
        assert (workspace / ".research/state.sqlite3").exists()

        # Another application's command is never overwritten.
        conflict = root / "conflict"
        conflict.mkdir()
        (conflict / "research").write_text("another application")
        run(
            "/bin/sh",
            str(installer),
            "--prefix",
            str(prefix),
            "--bin-dir",
            str(conflict),
            success=False,
        )
        assert (conflict / "research").read_text() == "another application"
        assert os.readlink(prefix / "current") == active

        # A damaged download is rejected before extraction/activation.
        damaged = root / "damaged.run"
        payload = bytearray(installer.read_bytes())
        payload[-20] ^= 1
        damaged.write_bytes(payload)
        result = run("/bin/sh", str(damaged), *install_args, success=False)
        assert "checksum failed" in result.stderr
        assert os.readlink(prefix / "current") == active
        print(
            json.dumps(
                {
                    "standalone": doctor["version"],
                    "bundled_node": doctor["node"],
                    "no_external_runtimes": True,
                    "relocation_with_spaces": True,
                    "hidden_persistent_config": True,
                    "real_pi_mcp_tool_loop": True,
                    "interactive_terminal": True,
                    "reinstall_and_damage_checks": True,
                }
            )
        )


if __name__ == "__main__":
    main()
