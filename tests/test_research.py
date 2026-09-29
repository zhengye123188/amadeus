import base64
import json

import httpx
import pytest
from conftest import approve, deny

from research_cli.research import ResearchTools, bm25, cosine, index_pages, rrf


async def test_import_search_exact_evidence_and_source_position(registry, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text(
        "Evidence about retrieval. BM25 uses term frequency.\nCode: https://github.com/example/project"
    )
    research = ResearchTools(registry)
    research.register()
    try:
        imported = await registry.invoke("import_document", '{"path":"notes.txt"}', deny)
        source = imported["result"]
        found = (await registry.invoke("search_library", '{"query":"BM25"}', deny))["result"][
            "matches"
        ]
        assert found[0]["source_id"] == source["source_id"]
        assert found[0]["position"] == {"page": 1, "char_start": 0}
        args = {
            "chunk_id": found[0]["chunk_id"],
            "quote": "BM25 uses term frequency.",
            "claim": "Term frequency matters",
            "relation": "supports",
        }
        evidence = (await registry.invoke("save_evidence", json.dumps(args), approve))["result"]
        assert evidence["quote_verified"] is True
        assert evidence["semantic_support"] == "not_independently_verified"
        args["quote"] = "BM25 always wins."
        assert not (await registry.invoke("save_evidence", json.dumps(args), approve))["ok"]
        links = await research.find_code_links({"source_id": source["source_id"]})
        assert links["links"] == ["https://github.com/example/project"]
        again = await research.import_document({"path": "notes.txt"})
        assert again["source_id"] == source["source_id"]
        assert registry.store.db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 1
    finally:
        await research.close()


def test_index_page_offsets_and_idempotent_download(store):
    pages = ["first", "x" * 2500]
    result = index_pages(store, pages, "test", {"url": "https://example.org", "retrieved_at": 1})
    repeat = index_pages(store, pages, "test", {"url": "https://example.org", "retrieved_at": 2})
    assert repeat["source_id"] == result["source_id"]
    rows = list(store.db.execute("SELECT position FROM chunks ORDER BY id"))
    assert json.loads(rows[-1][0]) == {"page": 2, "char_start": 1600}
    with pytest.raises(ValueError, match="No extractable"):
        index_pages(store, ["", " "], "blank", {})


def test_retrieval_handles_zero_overlap_and_chinese():
    assert bm25("unknown", ["BM25 retrieval", "transformer model"]) == [0, 0]
    scores = bm25("检索增强", ["检索增强生成的评测", "图像分割模型"])
    assert scores[0] > scores[1]
    assert cosine([1, 0], [0, 1]) == 0
    assert cosine([1, 0], [1, 0]) == 1
    assert rrf([["a", "b"], ["b"]])["b"] > rrf([["a", "b"], ["b"]])["a"]


async def test_crossref_metadata_and_github_commit_requests(registry, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-only-token")
    calls = []
    sha = "a" * 40

    def handler(request):
        calls.append(request)
        if request.url.host == "api.crossref.org":
            assert "authorization" not in request.headers
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [
                            {
                                "DOI": "10.0/test",
                                "title": ["Fixture paper"],
                                "URL": "https://doi.org/10.0/test",
                            }
                        ]
                    }
                },
            )
        assert request.headers["authorization"] == "Bearer test-only-token"
        if request.url.path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": sha})
        if request.url.path.endswith("/readme"):
            assert request.url.params["ref"] == sha
            return httpx.Response(200, json={"content": base64.b64encode(b"README").decode()})
        return httpx.Response(
            200,
            json={
                "default_branch": "main",
                "html_url": "https://github.com/example/repo",
                "archived": False,
            },
        )

    research = ResearchTools(registry, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        papers = await research.search_papers(
            {"query": "retrieval", "limit": 2, "from_year": 2023, "to_year": 2026}
        )
        assert papers["papers"][0]["level"] == "metadata"
        assert "from-pub-date:2023" in calls[0].url.params["filter"]
        repo = await research.inspect_repository({"repository": "https://github.com/example/repo"})
        assert repo["commit"] == sha
        assert repo["paper_relationship"].startswith("unverified")
    finally:
        await research.close()
