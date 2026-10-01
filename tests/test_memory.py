import json

import pytest

from research_cli.memory import MemoryUpdate, MemoryWrite, ProjectMemory
from research_cli.research import ResearchTools, index_pages


async def test_explicit_human_review_is_revision_bound_and_new_edits_reset_it(registry):
    memory = ProjectMemory(registry)
    row = await memory.save(
        MemoryWrite(kind="constraint", text="Use CPU only", status="active").model_dump()
    )
    reviewed = memory.human_review(
        {"memory_id": row["memory_id"], "expected_revision": 1, "decision": "confirm"}
    )
    assert reviewed["review_state"] == "human_confirmed" and reviewed["revision"] == 2
    with pytest.raises(ValueError, match="revision conflict"):
        memory.human_review(
            {"memory_id": row["memory_id"], "expected_revision": 1, "decision": "confirm"}
        )
    updated = await memory.save(
        MemoryUpdate(
            kind="constraint",
            text="Use GPU after approval",
            status="active",
            memory_id=row["memory_id"],
            expected_revision=2,
        ).model_dump()
    )
    assert updated["review_state"] == "unreviewed" and updated["revision"] == 3


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


async def test_literature_verdict_requires_claim_relation_and_explicit_assessment(registry):
    memory = ProjectMemory(registry)
    source = index_pages(
        registry.store, ["The method improves recall on this benchmark."], "fixture", {}
    )
    chunk = registry.store.db.execute(
        "SELECT id FROM chunks WHERE source=?", (source["source_id"],)
    ).fetchone()[0]
    research = ResearchTools(registry)
    try:
        evidence = await research.save_evidence(
            {
                "chunk_id": chunk,
                "quote": "improves recall",
                "claim": "Recall improves on this benchmark",
                "relation": "context",
            }
        )
        args = MemoryWrite(
            kind="hypothesis",
            text="Recall improves on this benchmark",
            status="supported",
            evidence_ids=[evidence["evidence_id"]],
        ).model_dump()
        with pytest.raises(ValueError, match="explicit assessment"):
            await memory.save(args)
        args["assessment"] = {
            "condition": "Recall exceeds the reported baseline on this benchmark",
            "rationale": "The cited benchmark report describes higher recall",
            "metric_checks": [],
        }
        with pytest.raises(ValueError, match="matching supports"):
            await memory.save(args)
        evidence = await research.save_evidence(
            {
                "chunk_id": chunk,
                "quote": "improves recall",
                "claim": args["text"],
                "relation": "supports",
            }
        )
        args["evidence_ids"] = [evidence["evidence_id"]]
        saved = await memory.save(args)
        assert saved["review_state"] == "model_reviewed"
        assert "independent review" in saved["verification"]
        registry.store.db.execute("UPDATE chunks SET text='changed' WHERE id=?", (chunk,))
        registry.store.db.commit()
        with pytest.raises(ValueError, match="no longer matches"):
            await memory.save(args)
    finally:
        await research.close()


async def test_metric_conditions_cannot_be_promoted_against_observed_values(registry):
    import sys

    from research_cli.jobs import Jobs, Run

    memory = ProjectMemory(registry)
    registry.settings.execution = "local"
    (registry.store.workspace / "data.json").write_text("[1, 2, 3]")
    jobs = Jobs(registry)
    spec = {
        "group": "mean-check",
        "variant": "baseline",
        "dataset": {
            "dataset_id": "three-values",
            "files": ["data.json"],
            "split": "all",
            "protocol": "Mean of all fixed values",
        },
        "seed": 0,
        "metrics": {
            "mean": {"direction": "maximize", "definition": "Arithmetic mean of recorded values"}
        },
        "primary_metric": "mean",
    }
    args = Run(
        argv=[
            sys.executable,
            "-c",
            "import json,pathlib; x=json.loads(pathlib.Path('data.json').read_text()); pathlib.Path('metrics.json').write_text(json.dumps({'mean':sum(x)/len(x)}))",
        ],
        spec=spec,
        timeout_seconds=10,
    ).model_dump()
    job = await jobs.start(args)
    await jobs.tasks[job["job_id"]]
    claim = MemoryWrite(
        kind="hypothesis",
        text="Mean is at least three",
        status="supported",
        job_ids=[job["job_id"]],
        assessment={
            "condition": "Measured mean >= 3",
            "rationale": "Check generated metric",
            "metric_checks": [
                {"job_id": job["job_id"], "metric": "mean", "operator": "gte", "threshold": 3}
            ],
        },
    ).model_dump()
    with pytest.raises(ValueError, match="contradicts the recorded"):
        await memory.save(claim)
    claim["status"] = "refuted"
    result = await memory.save(claim)
    assert result["review_state"] == "model_reviewed"
    claim["status"] = "supported"
    claim["assessment"]["metric_checks"][0]["threshold"] = 2
    assert (await memory.save(claim))["status"] == "supported"
    path = registry.store.root / "jobs" / job["job_id"] / "work/metrics.json"
    path.write_text('{"mean":20}')
    with pytest.raises(ValueError, match="no longer matches"):
        await memory.save(claim)
    await jobs.close()


async def test_process_failure_can_only_be_an_execution_observation(registry):
    memory = ProjectMemory(registry)
    registry.store.put("jobs", "job_failed", {"status": "failed", "exit_code": 1})
    record = MemoryWrite(
        kind="negative_result",
        text="Process failed; scientific outcome remains unknown",
        status="observed",
        job_ids=["job_failed"],
    ).model_dump()
    with pytest.raises(ValueError, match="no verified"):
        await memory.save(record)
    record["observation_type"] = "execution"
    assert (await memory.save(record))["observation_type"] == "execution"


async def test_v02_memory_context_preserves_legacy_records_without_claim_promotion(registry):
    memory = ProjectMemory(registry)
    legacy = {
        "memory_id": "mem_v02",
        "revision": 1,
        "kind": "hypothesis",
        "text": "Legacy retrieval claim",
        "status": "supported",
        "evidence_ids": [],
        "source_ids": [],
        "job_ids": [],
        "session_id": "old-session",
        "updated": 1,
        "verification": "References exist; scientific interpretation is not independently verified.",
    }
    encoded = json.dumps(legacy)
    with registry.store.db:
        registry.store.db.execute(
            "INSERT INTO research_memory VALUES(?,?,?)", (legacy["memory_id"], encoded, 1)
        )
        registry.store.db.execute(
            "INSERT INTO memory_revisions VALUES(?,?,?)", (legacy["memory_id"], 1, encoded)
        )
    context = await memory.context({"query": "retrieval", "limit": 5, "max_chars": 3000})
    record = context["records"][0]
    assert record["review_state"] == "unreviewed"
    assert record["assessment"] is None
    assert record["observation_type"] == "legacy_unclassified"
    assert record["status"] == "supported" and record["revision"] == 1
    retrieved = await memory.record({"kind": "memory", "record_id": legacy["memory_id"]})
    assert retrieved["history"] == [legacy]
    assert (
        registry.store.db.execute(
            "SELECT body FROM research_memory WHERE id=?", (legacy["memory_id"],)
        ).fetchone()[0]
        == encoded
    )
