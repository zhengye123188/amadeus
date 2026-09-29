from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.panel import Panel

from research_cli import __version__
from research_cli.config import Settings
from research_cli.extensions import MCPConnections, register_embeddings, register_jev
from research_cli.jobs import Jobs
from research_cli.providers import DemoProvider, OpenAIProvider
from research_cli.research import ResearchTools
from research_cli.runtime import Runtime
from research_cli.storage import Store, encode
from research_cli.tools import BUILTIN_SKILLS, Registry, register_files
from research_cli.types import AgentError

COMMANDS = [
    "/help",
    "/new",
    "/sessions",
    "/resume",
    "/context",
    "/compact",
    "/model",
    "/tools",
    "/skills",
    "/jobs",
    "/evidence",
    "/diff",
    "/permissions",
    "/cost",
    "/remember",
    "/import",
    "/cancel",
    "/stop",
    "/trace",
    "/exit",
]


def plain(text: str) -> str:
    """Keep model/tool-controlled terminal escape sequences out of the terminal."""
    return "".join(
        c
        for c in text
        if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127 and not 128 <= ord(c) < 160)
    )


class Display:
    def __init__(self, json_mode=False):
        self.json_mode = json_mode
        self.console = Console(highlight=False)
        self.streaming = False

    def say(self, text, style=None):
        if self.streaming:
            self.console.print()
            self.streaming = False
        self.console.print(plain(str(text)), style=style, markup=False)

    def data(self, value):
        self.say(json.dumps(value, ensure_ascii=False, indent=2))

    async def event(self, event):
        if self.json_mode:
            print(encode(event), flush=True)
            return
        kind = event["type"]
        if kind == "text_delta":
            if not self.streaming:
                self.console.print("agent › ", end="", style="cyan")
                self.streaming = True
            self.console.print(plain(event["text"]), end="", markup=False, highlight=False)
        elif kind == "tool_started":
            self.say(f"  ↳ {event['tool']}  {event['arguments'][:240]}", "dim")
        elif kind == "tool_finished":
            result = event["result"]
            self.say(
                f"  {'✓' if result['ok'] else '✗'} {event['tool']}  "
                + ("saved" if result["ok"] else str(result.get("detail", result.get("error")))),
                "green" if result["ok"] else "yellow",
            )
        elif kind in {"error", "cancelled"}:
            self.say(event["detail"], "yellow")
        elif kind == "turn_finished":
            cost = event["estimated_cost"]
            self.say(
                f"  [{event['status']}] {event['elapsed_seconds']}s · cost "
                + ("unknown" if cost is None else f"{cost:.6f}"),
                "dim",
            )


class Application:
    def __init__(self, store, settings, provider, display, sid):
        self.store, self.settings, self.provider, self.display = store, settings, provider, display
        self.registry = Registry(store, settings)
        register_files(self.registry)
        self.research = ResearchTools(self.registry)
        self.research.register()
        self.jobs = Jobs(self.registry)
        self.jobs.register()
        register_embeddings(self.registry, provider)
        register_jev(self.registry)
        self.mcp = MCPConnections(self.registry)
        self.runtime = Runtime(store, self.registry, provider, sid)
        self.pending_approval: asyncio.Future | None = None
        self.task: asyncio.Task | None = None
        self.queue: list[str] = []

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await self.task
        await self.jobs.close()
        await self.mcp.close()
        await self.research.close()
        await self.provider.close()

    async def approve(self, tool, args):
        self.pending_approval = asyncio.get_running_loop().create_future()
        self.display.say(f"Approve {tool}? Type y or n. /stop cancels.", "yellow")
        self.display.data(args)
        try:
            return await self.pending_approval
        finally:
            self.pending_approval = None

    async def deny(self, tool, args):
        return False

    async def submit(self, text):
        self.queue.append(text)
        if self.task and not self.task.done():
            self.display.say(
                "Queued. Use /stop to cancel the active turn; queued input will run next.", "dim"
            )
            return
        self.start_next()

    def start_next(self):
        if not self.queue:
            return
        prompt = self.queue.pop(0)
        self.task = asyncio.create_task(self.runtime.run(prompt, self.display.event, self.approve))

    async def command(self, line):
        command, _, rest = line.partition(" ")
        active = self.task is not None and not self.task.done()
        if command in {"/exit", "/quit"}:
            return False
        if command == "/stop":
            if active:
                self.task.cancel()
                await self.task
            self.display.say("Active turn stopped. Existing experiments are listed in /jobs.")
            return True
        if command == "/cancel":
            self.display.data(await self.jobs.cancel({"job_id": rest.strip()}))
            return True
        if (
            command
            in {"/new", "/resume", "/compact", "/model", "/permissions", "/import", "/remember"}
            and active
        ):
            self.display.say("Use /stop before changing session, configuration or context.")
            return True
        if command == "/help":
            self.display.say(
                "/new [title] · /sessions · /resume ID · /context · /compact\n"
                "/tools · /skills · /jobs · /cancel JOB_ID · /evidence · /diff\n"
                "/import PATH · /remember KEY TEXT · /model [NAME]\n"
                "/permissions [read-only|ask|workspace-write] · /cost · /trace\n"
                "/stop stops the current turn; /exit also stops owned experiments.\n"
                "Esc / Ctrl-C: interrupt. Enter: submit. Alt-Enter: newline.\n"
                "Type while running to queue follow-up input; for immediate steering, /stop first."
            )
        elif command == "/new":
            sid = self.store.create_session(rest or "Untitled")
            self.runtime = Runtime(self.store, self.registry, self.provider, sid)
            self.display.say("Session " + sid)
        elif command == "/sessions":
            self.display.data(self.store.sessions())
        elif command == "/resume":
            self.store.session(rest.strip())
            self.runtime = Runtime(self.store, self.registry, self.provider, rest.strip())
            self.display.say("Resumed " + rest.strip())
        elif command == "/context":
            self.display.data(
                {
                    "session": self.store.session(self.runtime.sid),
                    "notes": self.store.notes(),
                    "context_chars": self.settings.context_chars,
                }
            )
        elif command == "/compact":
            self.display.data(self.runtime.context.compact())
        elif command == "/tools":
            self.display.data(
                [
                    {"name": t.name, "effect": t.effect, "network": t.network}
                    for t in self.registry.tools.values()
                ]
            )
        elif command == "/skills":
            self.display.data({k: v[0] for k, v in BUILTIN_SKILLS.items()})
        elif command == "/jobs":
            self.display.data(self.store.records("jobs"))
        elif command == "/evidence":
            self.display.data(self.store.records("evidence"))
        elif command == "/trace":
            self.display.data(self.store.events(self.runtime.sid, 30))
        elif command == "/cost":
            self.display.data(
                [
                    e
                    for e in self.store.events(self.runtime.sid, 2000)
                    if e["type"] == "turn_finished"
                ]
            )
        elif command == "/permissions":
            if rest:
                if rest not in {"read-only", "ask", "workspace-write"}:
                    raise ValueError("Expected read-only, ask or workspace-write")
                self.settings.permission = rest
            self.display.say(
                f"permission={self.settings.permission}; execution={self.settings.execution}"
            )
        elif command == "/model":
            if rest:
                self.settings.model = rest.strip()
            self.display.say(f"api={self.settings.api}; model={self.settings.model or '(demo)'}")
        elif command == "/remember":
            key, sep, content = rest.partition(" ")
            if not sep or not content:
                raise ValueError("Usage: /remember KEY TEXT")

            async def yes(name, args):
                return True

            self.display.data(
                await self.registry.invoke("remember", encode({"key": key, "text": content}), yes)
            )
        elif command == "/import":
            parts = shlex.split(rest)
            if len(parts) != 1:
                raise ValueError("Usage: /import 'path to document'")
            self.display.data(
                await self.registry.invoke("import_document", encode({"path": parts[0]}), self.deny)
            )
        elif command == "/diff":
            self.display.data(await self.registry.invoke("git_diff", "{}", self.deny))
        else:
            self.display.say("Unknown command. /help")
        return True

    async def interactive(self):
        d = self.display
        d.console.print(
            Panel(
                f"ResearchCLI {__version__}\n{self.store.workspace}\nSession: {self.runtime.sid}\n"
                + (
                    "DEMO — deterministic tool exercise; no AI model\n"
                    if self.settings.api == "demo"
                    else f"Model: {self.settings.model}\n"
                )
                + "Natural language · /help · Esc to stop · Alt-Enter for newline",
                title="research",
                border_style="cyan",
            )
        )
        bindings = KeyBindings()

        @bindings.add("escape")
        def stop(event):
            if self.task and not self.task.done():
                self.task.cancel()

        @bindings.add("escape", "enter")
        def newline(event):
            event.current_buffer.insert_text("\n")

        session = PromptSession(
            history=FileHistory(str(self.store.root / "input.history")),
            completer=WordCompleter(COMMANDS),
            key_bindings=bindings,
        )
        prompt_task = None
        with patch_stdout(raw=True):
            try:
                while True:
                    if prompt_task is None:
                        prompt_task = asyncio.create_task(session.prompt_async("you › "))
                    waiters = {prompt_task}
                    if self.task:
                        waiters.add(self.task)
                    done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                    if self.task in done:
                        await self.task
                        self.task = None
                        self.start_next()
                    if prompt_task not in done:
                        continue
                    try:
                        line = prompt_task.result().strip()
                    except EOFError:
                        break
                    except KeyboardInterrupt:
                        if self.task and not self.task.done():
                            self.task.cancel()
                        else:
                            d.say("Use /exit or Ctrl-D to exit.")
                        continue
                    finally:
                        prompt_task = None
                    if not line:
                        continue
                    try:
                        if line.startswith("/"):
                            if not await self.command(line):
                                break
                        elif self.pending_approval is not None:
                            if line.lower() in {"y", "yes", "n", "no"}:
                                self.pending_approval.set_result(line.lower() in {"y", "yes"})
                            else:
                                d.say("Approval pending: type y/n, or /stop to redirect.")
                        else:
                            await self.submit(line)
                    except (ValueError, OSError) as exc:
                        d.say(str(exc), "yellow")
            finally:
                if prompt_task:
                    prompt_task.cancel()
                    await asyncio.gather(prompt_task, return_exceptions=True)


def parser():
    p = argparse.ArgumentParser(
        description="Interactive research agent. Natural language + dynamic tools."
    )
    p.add_argument("command", nargs="?", choices=["chat", "exec", "doctor"], default="chat")
    p.add_argument("prompt", nargs="?", help="Prompt for exec (or '-' for stdin)")
    p.add_argument("--workspace", type=Path, default=Path.cwd())
    p.add_argument("--config", type=Path, help="Explicit trusted TOML configuration")
    p.add_argument(
        "--demo", action="store_true", help="Deterministic offline tool demo, no AI inference"
    )
    p.add_argument("--model")
    p.add_argument("--api", choices=["responses", "chat"])
    p.add_argument("--resume", help="Session ID or 'last'")
    p.add_argument("--json", action="store_true", help="JSONL events for exec")
    p.add_argument("--permission", choices=["read-only", "ask", "workspace-write"])
    p.add_argument(
        "--execution",
        choices=["disabled", "docker", "local"],
        help="local is UNSANDBOXED; commands still need approval",
    )
    p.add_argument("--version", action="version", version=__version__)
    return p


async def run(args):
    if not args.workspace.is_dir():
        raise ValueError("Workspace does not exist")
    settings = Settings.load(args.config)
    for key in ["model", "api", "permission", "execution"]:
        if getattr(args, key):
            setattr(settings, key, getattr(args, key))
    if args.demo:
        settings.api = "demo"
    display = Display(args.json)
    if args.command == "doctor":
        display.data(
            {
                "version": __version__,
                "workspace": str(args.workspace.resolve()),
                "api": settings.api,
                "model": settings.model or "not configured",
                "api_key_present": bool(os.environ.get(settings.api_key_env)),
                "execution": settings.execution,
                "mcp_servers": [m.name for m in settings.mcp],
            }
        )
        return 0
    provider = DemoProvider() if settings.api == "demo" else OpenAIProvider(settings)
    store = Store(args.workspace)
    try:
        with store.lock():
            if args.resume:
                sid = (
                    store.sessions()[0]["id"]
                    if args.resume == "last" and store.sessions()
                    else args.resume
                )
                store.session(sid)
            else:
                sid = store.create_session(args.prompt or "Interactive session")
            app = Application(store, settings, provider, display, sid)
            try:
                await app.mcp.connect()
                if args.command == "exec":
                    prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
                    if not prompt:
                        raise ValueError("exec requires a prompt")
                    status = await app.runtime.run(prompt, display.event, app.deny)
                    return 0 if status == "completed" else 1
                if not sys.stdin.isatty():
                    raise ValueError(
                        "Interactive mode requires a terminal; use research exec PROMPT --json"
                    )
                await app.interactive()
                return 0
            finally:
                await app.close()
    finally:
        store.close()


def main():
    args = parser().parse_args()
    try:
        code = asyncio.run(run(args))
    except (AgentError, ValueError, OSError) as exc:
        print(f"research: {exc}", file=sys.stderr)
        code = 2
    except KeyboardInterrupt:
        code = 130
    raise SystemExit(code)
