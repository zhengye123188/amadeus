import asyncio
import io
import json
import os
import sys
from pathlib import Path

import pytest
from pypdf import PdfWriter

from research_cli import document_parser
from research_cli.research import ResearchTools


def pdf_bytes(pages=3):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def fake_bridge(tmp_path, monkeypatch, program):
    bridge = tmp_path / "parser.py"
    bridge.write_text(program)
    monkeypatch.setenv("RESEARCH_NODE", sys.executable)
    monkeypatch.setenv("RESEARCH_DOCUMENT_PARSER", str(bridge))
    return bridge


async def test_parser_keeps_blank_page_positions_and_extraction_provenance(
    registry, tmp_path, monkeypatch
):
    fake_bridge(
        tmp_path,
        monkeypatch,
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "assert request['expectedPages'] == 3\n"
        "assert open(request['inputPath'], 'rb').read(4) == b'%PDF'\n"
        "print(json.dumps({'parser':'pi-docparser','version':'4.0.0','ocr':False,"
        "'pages':['', 'Source-backed text on page two.', '']}))\n",
    )
    (tmp_path / "paper.pdf").write_bytes(pdf_bytes())
    research = ResearchTools(registry)
    try:
        result = await research.import_document({"path": "paper.pdf"})
        assert result["pages"] == 3
        assert result["provenance"]["extraction"] == document_parser.PARSER
        chunks = list(registry.store.db.execute("SELECT position,text FROM chunks"))
        assert len(chunks) == 1
        assert json.loads(chunks[0][0])["page"] == 2
        assert chunks[0][1] == "Source-backed text on page two."
        assert result["provenance"]["file_sha256"]
    finally:
        await research.close()


async def test_page_limit_rejects_before_starting_parser(tmp_path, monkeypatch):
    marker = tmp_path / "started"
    fake_bridge(tmp_path, monkeypatch, f"open({str(marker)!r}, 'w').write('yes')")
    with pytest.raises(ValueError, match="200-page"):
        await document_parser.parse_pdf_pages(pdf_bytes(201))
    assert not marker.exists()


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"parser": "other", "version": "4.0.0", "ocr": False, "pages": ["x"]}, "unsupported"),
        ({**document_parser.PARSER, "pages": ["x", "y"]}, "every PDF page"),
        ({**document_parser.PARSER, "pages": [None]}, "every PDF page"),
        ({**document_parser.PARSER, "pages": ["x" * 2_000_001]}, "2 million"),
    ],
)
def test_parser_rejects_wrong_engine_partial_pages_and_over_budget_text(payload, message):
    with pytest.raises((ValueError, RuntimeError), match=message):
        document_parser._validate_result(payload, 1)


async def test_missing_parser_fails_without_alternate_extraction(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_NODE", sys.executable)
    monkeypatch.setenv("RESEARCH_DOCUMENT_PARSER", str(tmp_path / "missing.mjs"))
    with pytest.raises(RuntimeError, match="bridge is missing"):
        await document_parser.parse_pdf_pages(pdf_bytes(1))


async def test_parser_failure_is_explicit(tmp_path, monkeypatch):
    fake_bridge(
        tmp_path,
        monkeypatch,
        "import sys\nsys.stderr.write('pi-docparser 4.0.0 is not installed')\nsys.exit(1)\n",
    )
    with pytest.raises(RuntimeError, match="pi-docparser 4.0.0 is not installed"):
        await document_parser.parse_pdf_pages(pdf_bytes(1))


async def test_timeout_stops_parser_and_removes_input(tmp_path, monkeypatch):
    marker = tmp_path / "running.json"
    fake_bridge(
        tmp_path,
        monkeypatch,
        "import json, os, sys, time\n"
        "request = json.load(sys.stdin)\n"
        f"open({str(marker)!r}, 'w').write(json.dumps({{'pid':os.getpid(), 'path':request['inputPath']}}))\n"
        "time.sleep(30)\n",
    )
    monkeypatch.setattr(document_parser, "PARSER_TIMEOUT", 0.5)
    with pytest.raises(RuntimeError, match="timed out"):
        await document_parser.parse_pdf_pages(pdf_bytes(1))
    running = json.loads(marker.read_text())
    assert not Path(running["path"]).exists()
    with pytest.raises(ProcessLookupError):
        os.kill(running["pid"], 0)


async def test_cancellation_stops_parser_and_preserves_cancelled_status(tmp_path, monkeypatch):
    marker = tmp_path / "running.json"
    fake_bridge(
        tmp_path,
        monkeypatch,
        "import json, os, sys, time\n"
        "request = json.load(sys.stdin)\n"
        f"open({str(marker)!r}, 'w').write(json.dumps({{'pid':os.getpid(), 'path':request['inputPath']}}))\n"
        "time.sleep(30)\n",
    )
    task = asyncio.create_task(document_parser.parse_pdf_pages(pdf_bytes(1)))
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.01)
    assert marker.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    running = json.loads(marker.read_text())
    assert not Path(running["path"]).exists()
    with pytest.raises(ProcessLookupError):
        os.kill(running["pid"], 0)
