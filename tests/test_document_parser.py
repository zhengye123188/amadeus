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


async def test_ocr_request_and_checked_provenance_are_attached_to_import(
    registry, tmp_path, monkeypatch
):
    expected = document_parser.extraction_provenance(True, ["eng", "chi_sim"])
    model_path = tmp_path / "models"
    fake_bridge(
        tmp_path,
        monkeypatch,
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "assert request['ocr'] is True\n"
        "assert request['ocrLanguages'] == ['eng', 'chi_sim']\n"
        f"assert request['tessdataPath'] == {str(model_path)!r}\n"
        f"print(json.dumps({{**{expected!r}, 'pages':['Recognized scan text.']}}))\n",
    )
    (tmp_path / "scan.pdf").write_bytes(pdf_bytes(1))
    research = ResearchTools(registry)
    try:
        result = await research.import_document(
            {
                "path": "scan.pdf",
                "ocr": True,
                "ocr_languages": ["eng", "chi_sim"],
                "tessdata_path": "models",
            }
        )
        assert result["provenance"]["extraction"] == expected
        assert "recognized text may contain errors" in result["extraction_note"]
        assert result["chunks"] == 1
    finally:
        await research.close()


async def test_ocr_limit_and_language_validation_reject_before_worker(tmp_path, monkeypatch):
    marker = tmp_path / "started"
    fake_bridge(tmp_path, monkeypatch, f"open({str(marker)!r}, 'w').write('yes')")
    with pytest.raises(ValueError, match="20 pages"):
        await document_parser.parse_pdf_pages(pdf_bytes(21), ocr=True)
    with pytest.raises(ValueError, match="distinct supported"):
        await document_parser.parse_pdf_pages(pdf_bytes(1), ocr=True, languages=["eng", "eng"])
    with pytest.raises(ValueError, match="distinct supported"):
        await document_parser.parse_pdf_pages(pdf_bytes(1), ocr=True, languages=["../secret"])
    assert not marker.exists()


async def test_tool_ocr_model_path_cannot_escape_workspace(registry, tmp_path):
    (tmp_path / "scan.pdf").write_bytes(pdf_bytes(1))
    research = ResearchTools(registry)
    try:
        with pytest.raises(ValueError, match="outside the workspace"):
            await research.import_document(
                {"path": "scan.pdf", "ocr": True, "tessdata_path": "../models"}
            )
        (tmp_path / "paper.txt").write_text("plain text")
        with pytest.raises(ValueError, match="PDF files only"):
            await research.import_document({"path": "paper.txt", "ocr": True})
    finally:
        await research.close()


def test_ocr_result_cannot_claim_wrong_language_model_or_disabled_recognition():
    expected = document_parser.extraction_provenance(True, ["eng"])
    wrong_model = {**expected, "ocr_data": [{"language": "eng", "sha256": "unknown"}]}
    for extraction in [document_parser.PARSER, wrong_model, {**expected, "ocr": 1}]:
        with pytest.raises(RuntimeError, match="unsupported extraction"):
            document_parser._validate_result({**extraction, "pages": ["scan text"]}, 1, expected)


async def test_ocr_is_available_offline_but_tool_schema_rejects_non_boolean_flags(
    registry, tmp_path, monkeypatch
):
    from conftest import deny

    expected = document_parser.extraction_provenance(True)
    fake_bridge(
        tmp_path,
        monkeypatch,
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "assert request['ocr'] is True\n"
        f"print(json.dumps({{**{expected!r}, 'pages':['local offline OCR fixture']}}))\n",
    )
    registry.settings.allow_network = False
    (tmp_path / "scan.pdf").write_bytes(pdf_bytes(1))
    research = ResearchTools(registry)
    research.register()
    try:
        tool = registry.tools["import_document"]
        assert tool.schema["properties"]["ocr"]["type"] == "boolean"
        assert tool.schema["properties"]["ocr"]["default"] is False
        assert tool.network is False
        result = await registry.invoke("import_document", '{"path":"scan.pdf","ocr":true}', deny)
        assert result["ok"] is True
        assert result["result"]["provenance"]["extraction"] == expected
        for invalid in ['"true"', "1"]:
            result = await registry.invoke(
                "import_document", '{"path":"scan.pdf","ocr":' + invalid + "}", deny
            )
            assert result["error"] == "invalid_arguments"
    finally:
        await research.close()


def test_explicit_ocr_config_and_managed_cache_path(tmp_path, monkeypatch):
    from research_cli.config import Settings

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("RESEARCH_OCR_TESSDATA", raising=False)
    assert document_parser.default_tessdata_path() == tmp_path / "config/research-cli/tessdata"
    monkeypatch.setenv("RESEARCH_OCR_TESSDATA", str(tmp_path / "trusted-ocr-models"))
    assert document_parser.default_tessdata_path() == tmp_path / "trusted-ocr-models"
    assert Settings.load().ocr_tessdata_path == str(tmp_path / "trusted-ocr-models")


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
