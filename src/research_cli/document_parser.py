"""Bridge PDF extraction to the bundled Pi document parser.

pypdf remains a cheap page-count preflight; all extracted text comes from
pi-docparser's isolated LiteParse worker. There is no alternate text extractor.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import tempfile
from pathlib import Path

PARSER = {"parser": "pi-docparser", "version": "4.0.0", "ocr": False}
MAX_BYTES = 20_000_000
MAX_PAGES = 200
MAX_CHARACTERS = 2_000_000
PARSER_TIMEOUT = 135.0
TEARDOWN_TIMEOUT = 10.0


def _page_count(data: bytes) -> int:
    from pypdf import PdfReader

    count = len(PdfReader(io.BytesIO(data)).pages)
    if count > MAX_PAGES:
        raise ValueError("PDF exceeds the 200-page import limit")
    if count < 1:
        raise ValueError("PDF contains no pages")
    return count


def _command() -> list[str]:
    node = os.environ.get("RESEARCH_NODE") or shutil.which("node")
    if not node:
        raise RuntimeError(
            "PDF extraction requires Node.js >=22.19 and pi-docparser 4.0.0. "
            "Install Research CLI with npm or its standalone installer."
        )
    configured = os.environ.get("RESEARCH_DOCUMENT_PARSER")
    bridge = (
        Path(configured).expanduser()
        if configured
        else Path(__file__).resolve().parents[2] / "bin" / "document-parser.mjs"
    )
    if not bridge.is_file():
        raise RuntimeError(
            "The bundled pi-docparser bridge is missing. Start this backend through research, "
            "or set RESEARCH_DOCUMENT_PARSER to bin/document-parser.mjs."
        )
    return [node, str(bridge.resolve())]


def _validate_result(payload: object, expected_pages: int) -> list[str]:
    if not isinstance(payload, dict) or any(payload.get(k) != v for k, v in PARSER.items()):
        raise RuntimeError("Document parser returned an unsupported extraction format")
    pages = payload.get("pages")
    if (
        not isinstance(pages, list)
        or len(pages) != expected_pages
        or any(not isinstance(page, str) for page in pages)
    ):
        raise RuntimeError("Document parser did not preserve every PDF page")
    if sum(map(len, pages)) > MAX_CHARACTERS:
        raise ValueError("Extracted text exceeds 2 million characters")
    return pages


async def _stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=TEARDOWN_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()


async def parse_pdf_pages(data: bytes) -> list[str]:
    """Extract all PDF pages locally, retaining blank pages and import budgets."""
    if len(data) > MAX_BYTES:
        raise ValueError("Document must be a regular file up to 20 MB")
    if not data.startswith(b"%PDF"):
        raise ValueError("Document is not a PDF")
    count = await asyncio.to_thread(_page_count, data)
    command = _command()
    with tempfile.TemporaryDirectory(prefix="research-pdf-") as directory:
        input_path = Path(directory) / "input.pdf"
        input_path.write_bytes(data)
        request = json.dumps({"inputPath": str(input_path), "expectedPages": count}).encode()
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise RuntimeError(
                "Cannot start pi-docparser. Check RESEARCH_NODE and reinstall Research CLI."
            ) from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(request), timeout=PARSER_TIMEOUT
            )
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            # SIGTERM asks the bridge to abort the upstream NativeExecutor and
            # await its worker-tree teardown before we remove the input file.
            await asyncio.shield(_stop(process))
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RuntimeError("PDF extraction timed out; the parser was stopped") from exc
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace").strip()[-2000:]
            raise RuntimeError(f"pi-docparser failed: {detail or 'worker exited unexpectedly'}")
        # UTF-8 encoding and JSON escaping can use several bytes per character.
        if len(stdout) > MAX_CHARACTERS * 6 + 10_000:
            raise RuntimeError("Document parser response exceeded its output budget")
        try:
            payload = json.loads(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Document parser returned invalid JSON") from exc
        return _validate_result(payload, count)
