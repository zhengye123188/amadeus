import json
import os
import subprocess
import sys

import pytest

from research_cli.cli import Application, Display, plain
from research_cli.config import Settings
from research_cli.providers import DemoProvider


def test_exec_demo_json_and_resume(tmp_path):
    (tmp_path / "note.txt").write_text("fixture text")
    command = [sys.executable, "-m", "research_cli", "--demo", "--workspace", str(tmp_path)]
    first = subprocess.run(
        [*command, "exec", "read @note.txt", "--json"], capture_output=True, text=True, timeout=15
    )
    assert first.returncode == 0, first.stderr
    events = [json.loads(line) for line in first.stdout.splitlines()]
    assert events[-1]["status"] == "completed"
    tool = next(e for e in events if e["type"] == "tool_finished")
    assert "fixture text" in tool["result"]["result"]["text"]
    second = subprocess.run(
        [*command, "--resume", "last", "exec", "files", "--json"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout.splitlines()[0])["session_id"] == events[0]["session_id"]


def test_missing_key_has_actionable_error_without_traceback(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    result = subprocess.run(
        [sys.executable, "-m", "research_cli", "--workspace", str(tmp_path), "exec", "hello"],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert result.returncode == 2
    assert "OPENAI_API_KEY" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminal")
def test_interactive_terminal_unicode_multiline_and_exit(tmp_path):
    pexpect = pytest.importorskip("pexpect")
    env = {**os.environ, "TERM": "xterm-256color", "PROMPT_TOOLKIT_NO_CPR": "1"}
    child = pexpect.spawn(
        sys.executable,
        ["-m", "research_cli", "--demo", "--workspace", str(tmp_path)],
        encoding="utf-8",
        env=env,
        timeout=15,
        dimensions=(30, 120),
    )
    try:
        child.expect("you ›")
        child.sendline("列出文件")
        child.expect("completed")
        child.sendline("/help")
        child.expect("Enter: submit")
        child.send("你好")
        child.send("\x1b\r")  # Alt-Enter inserts a newline, not submit.
        child.sendline("第二行")
        child.expect("completed")
        child.sendline("/exit")
        child.expect(pexpect.EOF)
        child.close()
        assert child.exitstatus == 0
        from research_cli.storage import Store

        store = Store(tmp_path)
        try:
            messages = store.messages(store.sessions()[0]["id"])
            assert any(m.get("content") == "你好\n第二行" for m in messages)
        finally:
            store.close()
    finally:
        child.close(force=True)


async def test_input_queue_runs_followup_after_active_turn(store):
    import asyncio

    from research_cli.types import ModelReply

    started, release = asyncio.Event(), asyncio.Event()

    class BlockingDemo(DemoProvider):
        async def generate(self, messages, *args):
            started.set()
            await release.wait()
            return ModelReply(text="done", input_tokens=0, output_tokens=0)

    app = Application(
        store, Settings(api="demo"), BlockingDemo(), Display(), store.create_session()
    )
    try:
        await app.submit("first")
        await started.wait()
        await app.submit("new constraint")
        assert app.queue == ["new constraint"]
        await app.command("/stop")
        assert app.task.done()
        release.set()
        app.start_next()
        await app.task
        assert [m["content"] for m in store.messages(app.runtime.sid) if m["role"] == "user"] == [
            "first",
            "new constraint",
        ]
    finally:
        await app.close()


def test_untrusted_text_cannot_emit_terminal_escape_codes():
    assert "\x1b" not in plain("hello\x1b]52;c;bad\x07")
