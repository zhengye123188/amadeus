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
OCR_DATA_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
OCR_MODELS = {
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "chi_sim": "a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730",
    "chi_tra": "529c5b5797d64b126065cd55f2bb4c7fd7b15790798091b1ff259941a829330b",
}
MAX_BYTES = 20_000_000
MAX_PAGES = 200
MAX_OCR_PAGES = 20
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
            "Install Amadeus with npm or its standalone installer."
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


def extraction_provenance(ocr: bool = False, languages: list[str] | None = None) -> dict:
    if not isinstance(ocr, bool):
        raise ValueError("OCR must be an explicit boolean")
    if not ocr:
        return PARSER.copy()
    languages = ["eng"] if languages is None else languages
    if (
        not isinstance(languages, list)
        or not 1 <= len(languages) <= 3
        or any(
            not isinstance(language, str) or language not in OCR_MODELS for language in languages
        )
        or len(set(languages)) != len(languages)
    ):
        raise ValueError("OCR languages must be distinct supported codes: eng, chi_sim, chi_tra")
    return {
        **PARSER,
        "ocr": True,
        "ocr_engine": "tesseract",
        "ocr_languages": languages.copy(),
        "ocr_data": [
            {
                "language": language,
                "sha256": OCR_MODELS[language],
                "source": (
                    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/"
                    f"{OCR_DATA_COMMIT}/{language}.traineddata"
                ),
            }
            for language in languages
        ],
        "dpi": 150,
    }


def default_tessdata_path() -> Path:
    configured = os.environ.get("RESEARCH_OCR_TESSDATA")
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "research-cli"
        / "tessdata"
    ).resolve()


def _validate_result(
    payload: object, expected_pages: int, expected: dict | None = None
) -> list[str]:
    expected = PARSER if expected is None else expected
    if (
        not isinstance(payload, dict)
        or payload.get("ocr") is not expected["ocr"]
        or any(payload.get(k) != v for k, v in expected.items())
    ):
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


async def parse_pdf_pages(
    data: bytes,
    *,
    ocr: bool = False,
    languages: list[str] | None = None,
    tessdata_path: Path | None = None,
    provenance: dict | None = None,
) -> list[str]:
    """Extract all PDF pages locally, retaining blank pages and import budgets."""
    if len(data) > MAX_BYTES:
        raise ValueError("Document must be a regular file up to 20 MB")
    if not data.startswith(b"%PDF"):
        raise ValueError("Document is not a PDF")
    count = await asyncio.to_thread(_page_count, data)
    expected = extraction_provenance(ocr, languages)
    if ocr and count > MAX_OCR_PAGES:
        raise ValueError("OCR imports are limited to 20 pages per document; split larger PDFs")
    command = _command()
    with tempfile.TemporaryDirectory(prefix="research-pdf-") as directory:
        input_path = Path(directory) / "input.pdf"
        input_path.write_bytes(data)
        arguments = {"inputPath": str(input_path), "expectedPages": count}
        if ocr:
            arguments.update(
                ocr=True,
                ocrLanguages=expected["ocr_languages"],
                tessdataPath=str((tessdata_path or default_tessdata_path()).resolve()),
            )
        request = json.dumps(arguments).encode()
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise RuntimeError(
                "Cannot start pi-docparser. Check RESEARCH_NODE and reinstall Amadeus."
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
        pages = _validate_result(payload, count, expected)
        if provenance is not None:
            provenance.update(expected)
        return pages
