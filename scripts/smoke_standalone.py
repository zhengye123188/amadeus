"""Install a real self-extractor without developer runtimes on PATH, then exercise Pi/MCP."""

from __future__ import annotations

import argparse
import io
import json
import os
import queue
import subprocess
import sys
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
                "XDG_DATA_HOME": str(root / "data"),
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
        packages = json.loads(run(research, "packages", "list").stdout)
        expected_packages = {
            "npm:pi-subagents@0.74.0": "delegation-engine",
            "npm:pi-docparser@4.0.0": "parser-engine",
            "npm:pi-web-access@0.35.0": "bundled-enabled",
            "npm:@upstash/context7-pi@0.1.2": "bundled-enabled",
        }
        assert {item["source"]: item["status"] for item in packages["bundled"]} == (
            expected_packages
        ), "Standalone installation is missing bundled Pi packages"
        bundle = (prefix / "current").resolve(strict=True)
        manifest = json.loads((bundle / "bundle.json").read_text())
        ui_resources = (
            "app/bin/interactive.mjs",
            "app/pi/ui.ts",
            "app/pi/themes/research-pixel.json",
            "app/pi/themes/research-mono.json",
            "app/pi/assets/kurisu-pixel.json",
            "app/pi/assets/kurisu-pixel.png",
        )
        for resource in ui_resources:
            assert (bundle / resource).is_file(), f"Missing bundled UI resource: {resource}"
            assert manifest["files"].get(resource, {}).get("sha256"), (
                f"UI resource is missing from the installer manifest: {resource}"
            )
        ocr = json.loads(run(research, "ocr", "list").stdout)
        assert all(item["status"] == "ready" for item in ocr["models"])
        assert Path(ocr["directory"]).is_relative_to(bundle)
        for item in packages["bundled"]:
            assert Path(item["path"]).is_relative_to(bundle)
        # Package installation must retain npm/npx and use bundled Node with poisoned PATH.
        bundled_node = str(bundle / "runtime/node/bin/node")
        run(bundled_node, "--version")
        for executable in ("npm", "npx"):
            run(bundled_node, str(bundle / "runtime/node/bin" / executable), "--version")
        python_env = {**env, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
        subprocess.run(
            [
                doctor["python"],
                "-I",
                "-B",
                "-c",
                "import ssl, sqlite3, mcp, pydantic_core, cryptography.hazmat.bindings._rust; "
                "print('Bundled Python native imports OK')",
            ],
            env=python_env,
            check=True,
        )

        # Import through the installed backend and native parser; preserve blank page positions.
        pdf_env = {
            **python_env,
            "RESEARCH_NODE": str(bundle / "runtime/node/bin/node"),
            "RESEARCH_DOCUMENT_PARSER": str(bundle / "app/bin/document-parser.mjs"),
            "RESEARCH_OCR_TESSDATA": str(bundle / "app/ocr/tessdata"),
        }
        pdf_result = subprocess.run(
            [
                doctor["python"],
                "-I",
                "-B",
                "-c",
                """
import asyncio, json
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, NumberObject
from research_cli.config import Settings
from research_cli.storage import Store
from research_cli.tools import Registry
from research_cli.research import ResearchTools

writer = PdfWriter()
writer.add_blank_page(width=300, height=200)
page = writer.add_blank_page(width=300, height=200)
font = DictionaryObject({
    NameObject('/Type'): NameObject('/Font'),
    NameObject('/Subtype'): NameObject('/Type1'),
    NameObject('/BaseFont'): NameObject('/Helvetica'),
})
page[NameObject('/Resources')] = DictionaryObject({
    NameObject('/Font'): DictionaryObject({NameObject('/F1'): font}),
})
stream = DecodedStreamObject()
stream.set_data(b'BT /F1 12 Tf 20 150 Td (Standalone parser source on page two.) Tj ET')
page[NameObject('/Contents')] = writer._add_object(stream)
writer.write('source.pdf')

# An image-only scan needs OCR; no font, image library or external runtime.
glyphs = {
    'R': '11110 10001 10001 11110 10100 10010 10001',
    'E': '11111 10000 10000 11110 10000 10000 11111',
    'S': '01111 10000 10000 01110 00001 00001 11110',
    'A': '01110 10001 10001 11111 10001 10001 10001',
    'C': '01111 10000 10000 10000 10000 10000 01111',
    'H': '10001 10001 10001 11111 10001 10001 10001',
    'N': '10001 11001 11001 10101 10011 10011 10001',
}
width, height, scale = 1400, 260, 12
pixels = bytearray([255]) * width * height
for index, char in enumerate('RESEARCH SCAN'):
    for row, values in enumerate(glyphs.get(char, '').split()):
        for column, value in enumerate(values):
            if value == '1':
                for y in range(scale):
                    start = (70 + row * scale + y) * width + 80 + index * 7 * scale + column * scale
                    pixels[start:start + scale] = bytes(scale)
scan = PdfWriter()
scan_page = scan.add_blank_page(width=700, height=130)
image = DecodedStreamObject()
image.set_data(bytes(pixels))
image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
    NameObject('/Width'): NumberObject(width), NameObject('/Height'): NumberObject(height),
    NameObject('/ColorSpace'): NameObject('/DeviceGray'), NameObject('/BitsPerComponent'): NumberObject(8)})
scan_page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Scan'): scan._add_object(image)})})
scan_stream = DecodedStreamObject()
scan_stream.set_data(b'q 700 0 0 130 0 0 cm /Scan Do Q')
scan_page[NameObject('/Contents')] = scan._add_object(scan_stream)
scan.write('scan.pdf')

async def main():
    store = Store(Path.cwd())
    tools = ResearchTools(Registry(store, Settings(permission='workspace-write', allow_network=False)))
    try:
        result = await tools.import_document({'path': 'source.pdf'})
        chunks = [
            {'position': json.loads(row[0]), 'text': row[1]}
            for row in store.db.execute('SELECT position,text FROM chunks')
        ]
        scanned = await tools.import_document({'path': 'scan.pdf', 'ocr': True, 'ocr_languages': ['eng']})
        ocr_text = ' '.join(row[0] for row in store.db.execute('SELECT text FROM chunks WHERE source=?', (scanned['source_id'],)))
        print(json.dumps({'source': result, 'chunks': chunks, 'ocr': scanned, 'ocr_text': ocr_text}))
    finally:
        await tools.close()
        store.close()

asyncio.run(main())
""",
            ],
            cwd=workspace,
            env=pdf_env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert pdf_result.returncode == 0, pdf_result.stderr + pdf_result.stdout
        parsed = json.loads(pdf_result.stdout)
        assert parsed["source"]["pages"] == 2
        assert parsed["source"]["provenance"]["extraction"] == {
            "parser": "pi-docparser",
            "version": "4.0.0",
            "ocr": False,
        }
        assert parsed["chunks"] and all(
            chunk["position"]["page"] == 2 for chunk in parsed["chunks"]
        ), "Native parser lost the leading blank page"
        assert any("Standalone parser source" in chunk["text"] for chunk in parsed["chunks"])
        assert "RESEARCH SCAN" in " ".join(parsed["ocr_text"].split())
        assert parsed["ocr"]["provenance"]["extraction"]["ocr"] is True

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
                is_child = "Research child role:" in json.dumps(body.get("messages", []))
                child_has_result = any(
                    message.get("role") == "tool" for message in body.get("messages", [])
                )
                if is_child and not child_has_result:
                    name, arguments = "mcp__research__project_status", {}
                elif not is_child and number < 3:
                    name = "read" if number == 1 else "mcp__research__project_status"
                    arguments = {"path": "README.md"} if number == 1 else {}
                elif not is_child and number == 3:
                    name, arguments = (
                        "agent_tasks",
                        {
                            "tasks": [
                                {"role": "code", "task": "Inspect the shared workspace status."}
                            ]
                        },
                    )
                else:
                    name, arguments = None, None
                if name:
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
                chunk["choices"][0].update(delta={}, finish_reason="tool_calls" if name else "stop")
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
                [research, "--mode", "rpc", "--offline"],
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
                assert all(not e.get("isError") for e in tools), events
                assert any(e.get("toolName") == "agent_tasks" for e in tools), events
                assert len(requests) == 6 and not failures
                assert "completed" in json.dumps(tools)
                assert "Standalone fixture" in json.dumps(requests[-1])
                assert str(workspace) in json.dumps(requests[-1], ensure_ascii=False)
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
            ["--offline"],
            cwd=str(workspace),
            env={**env, "RESEARCH_UI_AVATAR": "off", "NO_COLOR": "1"},
            encoding="utf8",
            timeout=30,
            dimensions=(35, 120),
        )
        terminal_output = io.StringIO()
        terminal.logfile_read = terminal_output
        try:
            terminal.expect_exact(f"Research CLI {doctor['version']}")
            terminal.expect_exact("PIXEL LAB / KURISU")
            terminal.expect_exact("research ·")
            terminal.send("/research-status\r")
            terminal.expect_exact("sources")
            terminal.sendcontrol("d")
            terminal.expect(pexpect.EOF)
        finally:
            terminal.close(force=True)
        assert terminal.exitstatus == 0, "Interactive terminal did not exit cleanly"
        output = terminal_output.getvalue()
        assert "▀" not in output, "Avatar-off must not show the portrait or upstream Pi logo"
        assert "Press ctrl+o to show full startup help" not in output
        assert "\x1b[38;2;" not in output and "\x1b[48;2;" not in output, (
            "The installed shell wrapper must honor NO_COLOR"
        )

        # The dev Python only drives the test. The application and its backend must
        # execute from the installed bundle, with external runtimes still poisoned.
        ui_result = run(
            sys.executable,
            str(Path(__file__).resolve().with_name("smoke_ui.py")),
            "--node",
            bundled_node,
            "--cli",
            str(bundle / "app/bin/research.mjs"),
            "--python",
            doctor["python"],
        )
        ui_checks = json.loads(ui_result.stdout)
        assert all(
            ui_checks.get(check) is True
            for check in (
                "pixel_header",
                "default_pixel_avatar",
                "avatar_off",
                "interactive_avatar_toggle",
                "pixel_palette_after_new_and_reload",
                "system_palette_after_reload",
                "resume_named_filter_and_cancel",
            )
        ), ui_checks

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
                    "bundled_packages": sorted(expected_packages),
                    "native_pdf_import": True,
                    "native_ocr_import": True,
                    "real_pi_child_agent": True,
                    "no_external_runtimes": True,
                    "relocation_with_spaces": True,
                    "hidden_persistent_config": True,
                    "real_pi_mcp_tool_loop": True,
                    "interactive_terminal": True,
                    "terminal_cwd_is_workspace": True,
                    "bundled_ui_resources": list(ui_resources),
                    "standalone_pixel_ui": ui_checks,
                    "shell_wrapper_monochrome_no_pi_banner": True,
                    "reinstall_and_damage_checks": True,
                }
            )
        )


if __name__ == "__main__":
    main()
