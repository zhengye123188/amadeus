"""Exercise the branded terminal, shortcuts and Chinese input in a real isolated PTY."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pexpect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default=shutil.which("node"))
    parser.add_argument("--cli", type=Path, default=Path("bin/research.mjs"))
    parser.add_argument("--python", type=Path, default=Path(".venv/bin/python"))
    args = parser.parse_args()
    if not args.node:
        parser.error("Node must be available or passed through --node")
    cli = args.cli.resolve(strict=True)
    # Preserve the venv executable path: resolving its symlink selects base Python.
    backend = args.python.absolute()
    if not backend.is_file():
        parser.error("The backend Python executable does not exist")
    requests = []
    failures = []
    answer = "Chinese input and custom terminal editor work."

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            if self.headers.get("Authorization") != "Bearer ui-fixture-only":
                failures.append("The fixture received an unexpected authentication header")
                self.send_error(401)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length > 2_000_000:
                self.send_error(413)
                return
            requests.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, reason in [({"role": "assistant", "content": answer}, None), ({}, "stop")]:
                chunk = {
                    "id": "ui-fixture",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "fixture",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": reason}],
                }
                if reason:
                    chunk["usage"] = {
                        "prompt_tokens": 100,
                        "completion_tokens": 10,
                        "total_tokens": 110,
                    }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="research-ui-smoke-") as temporary:
            root = Path(temporary).resolve()
            workspace = root / "科研项目 空格"
            workspace.mkdir()
            (workspace / "README.md").write_text("UI fixture workspace", encoding="utf8")
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("RESEARCH_", "OPENAI_", "ANTHROPIC_", "PI_", "PYTHON"))
                and not key.endswith("_API_KEY")
            }
            env.update(
                {
                    "HOME": str(root / "home"),
                    "XDG_CONFIG_HOME": str(root / "config"),
                    "XDG_CACHE_HOME": str(root / "cache"),
                    "XDG_DATA_HOME": str(root / "data"),
                    "PI_CODING_AGENT_DIR": str(root / "agent"),
                    "PI_OFFLINE": "1",
                    "PI_TELEMETRY": "0",
                    "RESEARCH_SKIP_CONFIG": "1",
                    "RESEARCH_PYTHON": str(backend),
                    "OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                    "OPENAI_API_KEY": "ui-fixture-only",
                    "RESEARCH_MODEL": "fixture",
                    "RESEARCH_API": "chat",
                    "TERM": "xterm-256color",
                    "TERM_PROGRAM": "research-fixture-terminal",
                    "COLORTERM": "truecolor",
                    "RESEARCH_UI_AVATAR": "off",
                }
            )
            # Tool runners often set NO_COLOR; the fixture explicitly emulates truecolor.
            env.pop("NO_COLOR", None)
            for name in ("home", "config", "cache", "data", "agent"):
                (root / name).mkdir()
            (root / "agent/settings.json").write_text(
                json.dumps({"retry": {"enabled": False}}), encoding="utf8"
            )
            transcript = io.StringIO()
            terminal = pexpect.spawn(
                args.node,
                [str(cli), "--offline", "--permission", "workspace-write", "--name", "ui-fixture"],
                cwd=str(workspace),
                env=env,
                encoding="utf8",
                timeout=35,
                dimensions=(40, 120),
            )
            terminal.logfile_read = transcript
            checkpoints = [("startup", 0)]
            try:
                terminal.expect(re.compile("Research CLI", re.IGNORECASE))
                terminal.expect_exact("PIXEL LAB")
                terminal.expect_exact("research ·")
                assert "▀" not in transcript.getvalue(), (
                    "The upstream Pi logo must not flash before the Research header when avatar is off"
                )
                checkpoints.append(("project status", transcript.tell()))
                terminal.send("/research-status\r")
                terminal.expect_exact("sources")
                # A resize must preserve the editor and CLI command handling.
                terminal.setwinsize(35, 54)
                checkpoints.append(("model selector", transcript.tell()))
                terminal.send("/model\r")
                terminal.expect_exact("to cancel")
                terminal.send("\x1b")
                # Wait for the editor, not the selector's already-painted footer.
                terminal.expect_exact("Enter 发送")
                checkpoints.append(("Chinese prompt", transcript.tell()))
                terminal.send("请确认中文输入和科研项目工作区。\r")
                terminal.expect_exact(answer)
                terminal.setwinsize(40, 120)
                terminal.expect_exact("PIXEL LAB / KURISU")
                for command in ("/new", "/reload"):
                    start = transcript.tell()
                    checkpoints.append((command, start))
                    terminal.send(command + "\r")
                    terminal.expect_exact("PIXEL LAB / KURISU")
                    terminal.expect_exact("research ·")
                    terminal.send("/ui\r")
                    terminal.expect_exact("UI: pixel")
                    terminal.expect_exact("avatar: off")
                    assert "38;2;166;228;190" in transcript.getvalue()[start:], (
                        f"The mint pixel palette must remain active after {command}"
                    )
                checkpoints.append(("system theme", transcript.tell()))
                terminal.send("/ui theme system\r")
                terminal.send("/ui\r")
                terminal.expect_exact("UI: system")
                checkpoints.append(("system theme reload", transcript.tell()))
                terminal.send("/reload\r")
                terminal.expect_exact("PIXEL LAB / KURISU")
                terminal.expect_exact("research ·")
                start = transcript.tell()
                terminal.send("/ui\r")
                terminal.expect_exact("UI: system")
                assert "38;2;166;228;190" not in transcript.getvalue()[start:], (
                    "Reload must retain the selected system palette"
                )
                # Ctrl-D exits through the inherited Pi editor keybindings.
                terminal.sendcontrol("d")
                terminal.expect(pexpect.EOF)
            except pexpect.ExceptionPexpect as error:
                plain = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", transcript.getvalue())
                raise AssertionError(
                    f"UI fixture failed after {len(requests)} requests. Terminal tail:\n{plain[-6000:]}"
                ) from error
            finally:
                terminal.close(force=True)
            assert terminal.exitstatus == 0, "The custom terminal did not exit cleanly"
            assert len(requests) == 1 and not failures, failures
            payload = json.dumps(requests[0], ensure_ascii=False)
            assert "请确认中文输入和科研项目工作区。" in payload
            assert str(workspace) in payload, "The terminal cwd must be the project workspace"
            output = transcript.getvalue()
            assert "Failed to load extension" not in output
            assert "\x1b]1337;File=" not in output, "The terminal must not emit iTerm graphics"
            assert "\x1b_G" not in output, "The terminal must not emit Kitty graphics"
            assert "ui-fixture-only" not in output, "Credentials must not appear in the UI"
            if "▀" in output:
                index = output.index("▀")
                stage = next(name for name, start in reversed(checkpoints) if start <= index)
                sample = re.sub(
                    r"\x1b\[[0-?]*[ -/]*[@-~]", "", output[max(0, index - 1000) : index + 1000]
                )
                raise AssertionError(
                    f"Avatar-off emitted pixel blocks during {stage}. First occurrence:\n{sample}"
                )

            # The default portrait uses ordinary colored text rather than image protocols.
            avatar_log = io.StringIO()
            avatar_terminal = pexpect.spawn(
                args.node,
                [str(cli), "--offline", "--permission", "workspace-write"],
                cwd=str(workspace),
                env={**env, "RESEARCH_UI_AVATAR": "pixel"},
                encoding="utf8",
                timeout=35,
                dimensions=(35, 120),
            )
            avatar_terminal.logfile_read = avatar_log
            try:
                avatar_terminal.expect_exact("PIXEL LAB / KURISU")
                avatar_terminal.expect_exact("▀")
                avatar_terminal.expect_exact("research ·")
                avatar_terminal.send("/ui avatar off\r")
                avatar_terminal.send("/ui\r")
                avatar_terminal.expect_exact("avatar: off")
                avatar_terminal.sendcontrol("d")
                avatar_terminal.expect(pexpect.EOF)
            except pexpect.ExceptionPexpect as error:
                plain = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", avatar_log.getvalue())
                raise AssertionError(
                    f"Pixel avatar fixture failed. Terminal tail:\n{plain[-4000:]}"
                ) from error
            finally:
                avatar_terminal.close(force=True)
            assert avatar_terminal.exitstatus == 0
            assert "\x1b]1337;File=" not in avatar_log.getvalue()
            assert "\x1b_G" not in avatar_log.getvalue()
            assert len(requests) == 1, "UI commands must not request model generation"

            resume = pexpect.spawn(
                args.node,
                [str(cli), "--offline", "--resume"],
                cwd=str(workspace),
                env=env,
                encoding="utf8",
                timeout=35,
                dimensions=(35, 120),
            )
            try:
                resume.expect_exact("恢复会话")
                resume.expect_exact("ui-fixture")
                resume.sendcontrol("n")
                resume.expect_exact("Named")
                resume.send("\x1b")
                resume.expect(pexpect.EOF)
            finally:
                resume.close(force=True)
            assert resume.exitstatus == 0, "Cancelling the resume selector must exit cleanly"
            assert len(requests) == 1, "Session selection must not request model generation"
            print(
                json.dumps(
                    {
                        "real_terminal": True,
                        "temporary_user_state": True,
                        "project_cwd": True,
                        "pixel_header": True,
                        "research_status_command": True,
                        "resize_120_to_54_columns": True,
                        "model_picker_and_escape": True,
                        "chinese_prompt": True,
                        "avatar_off": True,
                        "default_pixel_avatar": True,
                        "interactive_avatar_toggle": True,
                        "pixel_palette_after_new_and_reload": True,
                        "system_palette_after_reload": True,
                        "resume_named_filter_and_cancel": True,
                        "ctrl_d_exit": True,
                    }
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
