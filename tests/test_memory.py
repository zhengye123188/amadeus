import json

import pytest

from research_cli.memory import MemoryUpdate, MemoryWrite, ProjectMemory
from research_cli.research import ResearchTools, index_pages


async def test_memory_provenance_revision_and_retirement(registry):
    memory = ProjectMemory(registry)
    record = await memory.save(
        MemoryWrite(
            kind="constraint", text="CPU only, no private data upload", status="active"
        ).model_dump()
    )
    update = MemoryUpdate(
        **{k: v for k, v in record.items() if k in MemoryWrite.model_fields},
        memory_id=record["memory_id"],
        expected_revision=1,
    )
    update.status = "retired"
    revised = await memory.save(update.model_dump())
    assert revised["revision"] == 2
    with pytest.raises(ValueError, match="revision conflict"):
        await memory.save(update.model_dump())
    context = await memory.context({"query": "continue", "limit": 5, "max_chars": 3000})
    assert not context["records"]
    full = await memory.record({"kind": "memory", "record_id": record["memory_id"]})
    assert len(full["history"]) == 2
    assert full["history"][0]["status"] == "active"


async def test_hypotheses_cannot_claim_missing_evidence(registry):
    memory = ProjectMemory(registry)
    args = MemoryWrite(
        kind="hypothesis", text="Reranking improves recall", status="supported"
    ).model_dump()
    with pytest.raises(ValueError, match="requires evidence"):
        await memory.save(args)
    args["evidence_ids"] = ["ev_invented"]
    with pytest.raises(ValueError, match="Unknown evidence"):
        await memory.save(args)
    args = MemoryWrite(
        kind="negative_result", text="The run failed", status="observed"
    ).model_dump()
    with pytest.raises(ValueError, match="requires a recorded experiment"):
        await memory.save(args)


async def test_context_budget_retains_constraint_and_exact_evidence(registry):
    memory = ProjectMemory(registry)
    source = index_pages(registry.store, ["A retrieval baseline needs ablations."], "fixture", {})
    chunk = registry.store.db.execute("SELECT id FROM chunks").fetchone()[0]
    research = ResearchTools(registry)
    try:
        ev = await research.save_evidence(
            {
                "chunk_id": chunk,
                "quote": "A retrieval baseline needs ablations.",
                "claim": "Test the baseline",
                "relation": "context",
            }
        )
    finally:
        await research.close()
    await memory.save(
        MemoryWrite(kind="constraint", text="Use only CPU", status="active").model_dump()
    )
    await memory.save(
        MemoryWrite(
            kind="hypothesis",
            text="retrieval improvement",
            status="proposed",
            evidence_ids=[ev["evidence_id"]],
            source_ids=[source["source_id"]],
        ).model_dump()
    )
    for i in range(20):
        await memory.save(
            MemoryWrite(
                kind="finding", text=f"Unrelated report {i} " + "x" * 1000, status="reported"
            ).model_dump()
        )
    ctx = await memory.context({"query": "retrieval", "limit": 3, "max_chars": 4000})
    assert len(json.dumps(ctx, ensure_ascii=False)) <= 4000
    assert ctx["records"][0]["kind"] == "constraint"
    assert ctx["evidence"][0]["quote_excerpt"] == ev["quote"]
    assert ctx["omitted_records"] > 0
    assert ctx["omitted_constraints"] == 0


async def test_repository_association_requires_same_source(registry):
    memory = ProjectMemory(registry)
    registry.store.put(
        "sources",
        "github_fixture",
        {"provider": "GitHub", "repository": "example/baseline", "commit": "a" * 40},
    )
    source = index_pages(
        registry.store, ["Code: https://github.com/example/baseline"], "fixture", {}
    )
    chunk = registry.store.db.execute("SELECT id FROM chunks").fetchone()[0]
    research = ResearchTools(registry)
    try:
        ev = await research.save_evidence(
            {
                "chunk_id": chunk,
                "quote": "https://github.com/example/baseline",
                "claim": "Code mentioned",
                "relation": "context",
            }
        )
    finally:
        await research.close()
    linked = await memory.link_repository(
        {
            "source_id": source["source_id"],
            "repository_source_id": "github_fixture",
            "repository": "example/baseline",
            "commit": "a" * 40,
            "evidence_id": ev["evidence_id"],
        }
    )
    assert "unverified" in linked["relationship"]
    with pytest.raises(ValueError, match="must match"):
        await memory.link_repository(
            {
                "source_id": source["source_id"],
                "repository_source_id": "github_fixture",
                "repository": "other/repo",
                "commit": "a" * 40,
                "evidence_id": ev["evidence_id"],
            }
        )
    other = index_pages(registry.store, ["Another source"], "other", {})
    with pytest.raises(ValueError, match="Association requires"):
        await memory.link_repository(
            {
                "source_id": other["source_id"],
                "repository_source_id": "github_fixture",
                "repository": "example/baseline",
                "commit": "a" * 40,
                "evidence_id": ev["evidence_id"],
            }
        )
