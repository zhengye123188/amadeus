import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from conftest import approve, deny
from openai import AsyncOpenAI

from research_cli.config import MCPServer
from research_cli.extensions import MCPConnections, register_embeddings, register_jev
from research_cli.research import index_pages


async def test_actual_mcp_stdio_discovery_validation_and_approval(registry):
    pytest.importorskip("mcp")
    server = Path(__file__).parents[1] / "examples" / "mcp_server.py"
    registry.settings.mcp = [MCPServer(name="demo", command=sys.executable, args=[str(server)])]
    connections = MCPConnections(registry)
    try:
        await connections.connect()
        tool = "mcp_demo_experiment_checklist"
        assert tool in registry.tools
        assert (await registry.invoke(tool, '{"topic":"retrieval"}', deny))[
            "error"
        ] == "permission_denied"
        result = await registry.invoke(tool, '{"topic":"retrieval"}', approve)
        assert result["ok"]
        assert "Freeze data split" in json.dumps(result)
        assert (await registry.invoke(tool, '{"topic":false}', approve))[
            "error"
        ] == "invalid_arguments"
    finally:
        await connections.close()


async def test_embeddings_sdk_and_hybrid_ranking(registry):
    registry.settings.embedding_model = "fixture-embedding"
    a = index_pages(registry.store, ["retrieval term matching"], "A", {"path": "a"})
    b = index_pages(registry.store, ["image segmentation"], "B", {"path": "b"})

    def handler(request):
        body = json.loads(request.content)
        # Explicit float encoding makes fixtures independent of SDK base64 optimizations.
        embeddings = [[1.0, 0.0] if "retrieval" in x else [0.0, 1.0] for x in body["input"]]
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "fixture-embedding",
                "data": [
                    {"object": "embedding", "index": i, "embedding": e}
                    for i, e in enumerate(embeddings)
                ],
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            },
        )

    client = AsyncOpenAI(
        api_key="test-only", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    register_embeddings(registry, SimpleNamespace(client=client))
    try:
        for source in [a, b]:
            result = await registry.invoke(
                "index_embeddings", json.dumps({"source_id": source["source_id"]}), approve
            )
            assert result["ok"], result
        result = await registry.invoke(
            "hybrid_search", '{"query":"retrieval","method":"hybrid"}', approve
        )
        assert result["ok"], result
        assert result["result"]["matches"][0]["source_id"] == a["source_id"]
        registry.settings.embedding_model = "different"
        result = await registry.invoke("hybrid_search", '{"query":"retrieval"}', approve)
        assert not result["ok"] and "matching embedding index" in result["detail"]
    finally:
        await client.close()


async def test_jev_real_sdk_request_shape_and_response(registry, monkeypatch):
    sdk = pytest.importorskip("typesafe_sdk")
    import httpx2

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    index_pages(registry.store, ["retrieval evidence"], "A", {})
    cid = registry.store.db.execute("SELECT id FROM chunks").fetchone()[0]
    original = sdk.AsyncTypeSafeClient

    def handler(request):
        body = json.loads(request.content)
        assert body["questions"]["chunk_0"]["type"] == "score"
        assert len(body["questions"]["chunk_0"]["criteria"]) == 5
        return httpx2.Response(
            200,
            json={
                "model": "fixture-jev",
                "usage": {"input_tokens": 10, "output_tokens": 1},
                "answers": {
                    "chunk_0": {
                        "type": "score",
                        "score": 3.7,
                        "confidence": 0.8,
                        "legend": {str(i): str(i) for i in range(5)},
                        "probabilities": {"3": 0.3, "4": 0.7},
                    }
                },
            },
        )

    monkeypatch.setattr(
        sdk,
        "AsyncTypeSafeClient",
        lambda **kwargs: original(transport=httpx2.MockTransport(handler), **kwargs),
    )
    register_jev(registry)
    result = await registry.invoke(
        "jev_rerank", json.dumps({"query": "retrieval", "chunk_ids": [cid]}), approve
    )
    assert result["ok"], result
    assert result["result"]["ranking"][0]["score"] == 3.7
    assert result["result"]["model"] == "fixture-jev"


async def test_jev_missing_key_fails_explicitly(registry, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    register_jev(registry)
    result = await registry.invoke("jev_rerank", '{"query":"x","chunk_ids":["x"]}', approve)
    assert not result["ok"]
    assert "no hidden fallback" in result["detail"]
