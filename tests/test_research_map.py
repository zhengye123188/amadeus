import asyncio
import hashlib
import json
import sys

import httpx
import pytest
from conftest import approve, deny

from research_cli.jobs import Jobs
from research_cli.research import ResearchTools, index_pages
from research_cli.research_map import PaperIdentity, ResearchMap, canonical_arxiv, canonical_doi


async def invoke(registry, name, args, ok=True):
    result = await registry.invoke(name, json.dumps(args), approve)
    assert result["ok"] == ok, result
    return result["result"] if ok else result


def paper_fixture(
    store,
    doi="10.1234/fixture",
    text="Accuracy on test split: 0.80. Code: https://github.com/example/code",
):
    identities = PaperIdentity(store)
    paper = identities.register(doi=doi, title="Fixture paper")
    source = index_pages(
        store, [text], "Fixture paper", {"fixture": doi}, paper_id=paper["paper_id"]
    )
    chunk = store.db.execute(
        "SELECT id FROM chunks WHERE source=?", (source["source_id"],)
    ).fetchone()[0]
    evidence = {
        "evidence_id": "ev_" + doi.replace("/", "_"),
        "source_id": source["source_id"],
        "chunk_id": chunk,
        "quote": text,
        "quote_verified": True,
        "relation": "supports",
    }
    store.put("evidence", evidence["evidence_id"], evidence)
    return paper, source, evidence


@pytest.mark.parametrize(
    "value",
    [
        "10.1234/ABC",
        "doi:10.1234/ABC",
        "https://doi.org/10.1234/ABC",
        "http://dx.doi.org/10.1234%2FABC",
    ],
)
def test_normalized_doi(value):
    assert canonical_doi(value) == "10.1234/abc"


def test_arxiv_identity_retains_versions_without_title_merges(store):
    assert canonical_arxiv("https://arxiv.org/pdf/2601.12345v2.pdf") == ("2601.12345", "v2")
    assert canonical_arxiv("arXiv:hep-th/9901001v1") == ("hep-th/9901001", "v1")
    with pytest.raises(ValueError):
        canonical_arxiv("2601.12345v0")
    identities = PaperIdentity(store)
    v1 = identities.register(arxiv_id="2601.12345v1", title="Same title")
    v2 = identities.register(arxiv_id="2601.12345v2", title="Same title")
    other = identities.register(arxiv_id="2601.99999", title="Same title")
    assert v1["paper_id"] == v2["paper_id"] != other["paper_id"]
    assert v2["arxiv_versions"] == ["v1", "v2"]
    assert identities.resolve(arxiv_id="2601.12345v1") == v1["paper_id"]
    identities.register(doi="10.1234/fixture", arxiv_id="2601.12345", expected_revision=2)
    assert identities.resolve(doi="HTTPS://DOI.ORG/10.1234/FIXTURE") == v1["paper_id"]
    with pytest.raises(ValueError, match="conflict"):
        identities.register(arxiv_id="2601.12345", title="Stale title", expected_revision=1)
    with pytest.raises(ValueError, match="different papers"):
        identities.register(doi="10.1234/fixture", arxiv_id="2601.99999")


async def test_fulltext_explicit_attachment_and_map_revision_guards(registry, tmp_path):
    maps = ResearchMap(registry)
    maps.register()
    research = ResearchTools(registry)
    research.register()
    try:
        identity = await invoke(registry, "register_paper_identity", {"doi": "10.1234/fixture"})
        (tmp_path / "paper.txt").write_text("The method uses BM25. Evaluation uses split A.")
        source = await invoke(
            registry, "import_document", {"path": "paper.txt", "paper_id": identity["paper_id"]}
        )
        assert source["paper_id"] == identity["paper_id"]
        repeated = await invoke(registry, "import_document", {"path": "paper.txt"})
        assert repeated["paper_id"] == identity["paper_id"]
        chunk = registry.store.db.execute(
            "SELECT id FROM chunks WHERE source=?", (source["source_id"],)
        ).fetchone()[0]
        ev = await invoke(
            registry,
            "save_evidence",
            {
                "chunk_id": chunk,
                "quote": "The method uses BM25.",
                "claim": "BM25 method",
                "relation": "supports",
            },
        )
        args = {
            "paper_id": identity["paper_id"],
            "fields": {"method": [{"text": "BM25", "evidence_ids": [ev["evidence_id"]]}]},
        }
        written = await invoke(registry, "save_research_map", args)
        assert written["revision"] == 1
        await invoke(registry, "save_research_map", args, ok=False)
        args["expected_revision"] = 1
        args["fields"]["limitations"] = [
            {"text": "Investigate vocabulary mismatch", "basis": "inference"}
        ]
        assert (await invoke(registry, "save_research_map", args))["revision"] == 2
        history = await invoke(registry, "read_research_map", {"paper_id": identity["paper_id"]})
        assert [r["revision"] for r in history["history"]] == [1, 2]
        other = await invoke(registry, "register_paper_identity", {"doi": "10.1234/other"})
        args.update(paper_id=other["paper_id"], expected_revision=0)
        denied = await invoke(registry, "save_research_map", args, ok=False)
        assert "this canonical paper" in denied["detail"]
        unknown = await invoke(registry, "get_paper_identity", {"doi": "10.1234/unknown"}, ok=False)
        assert "Unknown" in unknown["detail"]
        await invoke(
            registry,
            "save_research_map",
            {
                "paper_id": identity["paper_id"],
                "expected_revision": 2,
                "fields": {"method": [{"text": "unsupported reported method"}]},
            },
            ok=False,
        )
        registry.settings.permission = "read-only"
        assert not (
            await registry.invoke("register_paper_identity", '{"doi":"10.1234/readonly"}', approve)
        )["ok"]
        assert (await registry.invoke("list_papers", "{}", deny))["ok"]
    finally:
        await research.close()


async def test_comparison_and_exports_preserve_uncertainty(registry):
    maps = ResearchMap(registry)
    maps.register()
    p1, _, ev1 = paper_fixture(registry.store)
    p2, _, ev2 = paper_fixture(registry.store, "10.1234/second")
    for paper, evidence, split in [(p1, ev1, "test A"), (p2, ev2, "test B")]:
        await invoke(
            registry,
            "save_research_map",
            {
                "paper_id": paper["paper_id"],
                "fields": {"dataset": [{"text": split, "evidence_ids": [evidence["evidence_id"]]}]},
            },
        )
    args = {"paper_ids": [p1["paper_id"], p2["paper_id"]]}
    compared = await invoke(registry, "compare_papers", args)
    assert compared["comparability"] == "not_independently_verified"
    assert "dataset" in compared["warnings"][0]
    assert "limitations" in compared["missing_fields"][p1["paper_id"]]
    markdown = await invoke(registry, "export_research_map", {**args, "format": "markdown"})
    assert ev1["evidence_id"] in markdown["content"]
    assert registry.store.read_artifact(markdown["artifact_id"])["text"] == markdown["content"]
    exported = await invoke(registry, "export_research_map", {**args, "format": "bibtex"})
    assert "doi = {10.1234/fixture}" in exported["content"]
    assert "author =" not in exported["content"]
    exported_json = await invoke(registry, "export_research_map", {**args, "format": "json"})
    assert json.loads(exported_json["content"])["warnings"] == compared["warnings"]


async def test_identity_rejects_source_reassignment_and_repository_as_paper(registry):
    maps = ResearchMap(registry)
    p1, source, _ = paper_fixture(registry.store)
    p2 = maps.identities.register(doi="10.1234/other")
    with pytest.raises(ValueError, match="another paper"):
        maps.identities.attach(source["source_id"], p2["paper_id"])
    assert registry.store.get("sources", source["source_id"])["paper_id"] == p1["paper_id"]
    with pytest.raises(ValueError, match="another paper"):
        index_pages(
            registry.store,
            ["Accuracy on test split: 0.80. Code: https://github.com/example/code"],
            "Fixture paper",
            {"fixture": "10.1234/fixture"},
            paper_id=p2["paper_id"],
        )
    assert registry.store.get("sources", source["source_id"])["paper_id"] == p1["paper_id"]
    registry.store.put("sources", "repo", {"provider": "GitHub", "level": "repository_inspection"})
    with pytest.raises(ValueError, match="cannot be paper"):
        maps.identities.register(source_ids=["repo"])


async def test_reproduction_requires_real_metrics_pinned_code_and_protocol(registry, tmp_path):
    maps = ResearchMap(registry)
    maps.register()
    jobs = Jobs(registry)
    jobs.register()
    registry.settings.execution = "local"
    registry.settings.permission = "workspace-write"
    paper, _, evidence = paper_fixture(registry.store)
    commit = "a" * 40
    code = 'import json\nfrom pathlib import Path\njson.loads(Path("data.json").read_text())\nPath("metrics.json").write_text(json.dumps({"accuracy":0.8}))\n'
    (tmp_path / "train.py").write_text(code)
    (tmp_path / "data.json").write_text('[{"x":1,"y":0}]')
    registry.store.put(
        "sources",
        "repo",
        {
            "provider": "GitHub",
            "repository": "example/code",
            "commit": commit,
            "level": "repository_inspection",
        },
    )
    registry.store.put(
        "sources",
        "code",
        {
            "provider": "GitHub",
            "repository": "example/code",
            "commit": commit,
            "level": "repository_file",
            "path": "train.py",
            "content_sha256": hashlib.sha256(code.encode()).hexdigest(),
        },
    )
    plan_args = {
        "paper_id": paper["paper_id"],
        "repository_source_id": "repo",
        "commit": commit,
        "association_evidence_ids": [evidence["evidence_id"]],
        "code_source_ids": ["code"],
        "dependencies": ["Python standard library"],
        "data": ["data.json"],
        "dataset_id": "fixture",
        "split": "test",
        "protocol": "fixture protocol",
        "configuration": {"seed": "0"},
        "hardware": "CPU",
        "command": [sys.executable, "train.py"],
        "targets": [
            {
                "name": "accuracy",
                "value": 0.8,
                "tolerance": 0.01,
                "evidence_ids": [evidence["evidence_id"]],
            }
        ],
    }
    try:
        plan = await invoke(registry, "save_reproduction_plan", plan_args)
        assert plan["relationship"] == "mentioned_in_paper; authorship_unverified"
        assert plan["readiness_gaps"] == []
        stage_args = {
            "plan_id": plan["plan_id"],
            "expected_revision": 1,
            "stage": "baseline_completed",
            "note": "Fixture baseline",
        }
        assert (
            "completed recorded job"
            in (await invoke(registry, "update_reproduction_stage", stage_args, ok=False))["detail"]
        )
        run = await invoke(
            registry,
            "run_experiment",
            {
                "argv": plan_args["command"],
                "spec": {
                    "group": "fixture",
                    "variant": "baseline",
                    "dataset": {
                        "dataset_id": "fixture",
                        "files": ["data.json"],
                        "split": "test",
                        "protocol": "fixture protocol",
                    },
                    "seed": 0,
                    "parameters": {},
                    "metrics": {
                        "accuracy": {"direction": "maximize", "definition": "Fraction correct"}
                    },
                    "primary_metric": "accuracy",
                },
            },
        )
        for _ in range(100):
            job = registry.store.get("jobs", run["job_id"])
            if job["status"] not in {"starting", "running"}:
                break
            await asyncio.sleep(0.01)
        assert job["status"] == "completed"
        stage_args["job_id"] = job["job_id"]
        baseline = await invoke(registry, "update_reproduction_stage", stage_args)
        assert baseline["stage"] == "baseline_completed"
        stage_args.update(expected_revision=2, stage="metrics_matched")
        matched = await invoke(registry, "update_reproduction_stage", stage_args)
        assert matched["stage"] == "metrics_matched"
        assert matched["relationship"].endswith("authorship_unverified")
        # Plan changes invalidate past success instead of retaining a misleading stage.
        updated = await invoke(
            registry,
            "save_reproduction_plan",
            {
                **plan_args,
                "plan_id": plan["plan_id"],
                "expected_revision": 3,
                "protocol": "different protocol",
            },
        )
        assert updated["stage"] == "drafted"
        stage_args["expected_revision"] = 4
        assert (
            "protocol differs"
            in (await invoke(registry, "update_reproduction_stage", stage_args, ok=False))["detail"]
        )
        updated = await invoke(
            registry,
            "save_reproduction_plan",
            {**plan_args, "plan_id": plan["plan_id"], "expected_revision": 4},
        )
        assert updated["revision"] == 5
        # Tampering after capture cannot become successful reproduction evidence.
        (registry.store.root / "jobs" / job["job_id"] / "work" / "metrics.json").write_text(
            '{"accuracy":0.81}'
        )
        stage_args["expected_revision"] = 5
        assert (
            "no longer matches"
            in (await invoke(registry, "update_reproduction_stage", stage_args, ok=False))["detail"]
        )
        folder = registry.store.root / "jobs" / job["job_id"]
        (folder / "work" / "metrics.json").write_text(json.dumps({"accuracy": 0.8}))
        original_capture = job["experimental_results"]
        registry.store.put(
            "jobs", job["job_id"], {**job, "experimental_results": {"status": "not_requested"}}
        )
        assert (
            "no verified"
            in (await invoke(registry, "update_reproduction_stage", stage_args, ok=False))["detail"]
        )
        registry.store.put("jobs", job["job_id"], {**job, "experimental_results": original_capture})
        original_manifest = (folder / "manifest.json").read_text()
        manifest = json.loads(original_manifest)
        manifest["train.py"] = "0" * 64
        (folder / "manifest.json").write_text(json.dumps(manifest))
        assert (
            "manifest hash changed"
            in (await invoke(registry, "update_reproduction_stage", stage_args, ok=False))["detail"]
        )
        (folder / "manifest.json").write_text(original_manifest)
        registry.store.put(
            "sources",
            "code",
            {
                "provider": "GitHub",
                "repository": "example/code",
                "commit": commit,
                "level": "repository_file",
                "path": "train.py",
                "content_sha256": "0" * 64,
            },
        )
        assert (
            "does not match"
            in (await invoke(registry, "update_reproduction_stage", stage_args, ok=False))["detail"]
        )
    finally:
        await jobs.close()


async def test_reproduction_rejects_incomplete_preparation_commit_and_targets(registry):
    maps = ResearchMap(registry)
    maps.register()
    paper, _, ev = paper_fixture(registry.store)
    registry.store.put(
        "sources",
        "repo",
        {
            "provider": "GitHub",
            "repository": "example/code",
            "commit": "a" * 40,
            "level": "repository_inspection",
        },
    )
    plan = await invoke(
        registry,
        "save_reproduction_plan",
        {"paper_id": paper["paper_id"], "repository_source_id": "repo", "commit": "a" * 40},
    )
    assert plan["relationship"] == "candidate; association_unverified"
    args = {
        "plan_id": plan["plan_id"],
        "expected_revision": 1,
        "stage": "environment_ready",
        "note": "Cannot infer this from a README",
    }
    assert (
        "details missing"
        in (await invoke(registry, "update_reproduction_stage", args, ok=False))["detail"]
    )
    await invoke(
        registry,
        "save_reproduction_plan",
        {"paper_id": paper["paper_id"], "repository_source_id": "repo", "commit": "b" * 40},
        ok=False,
    )
    with pytest.raises(ValueError, match="target/tolerance"):
        maps.match_metrics(
            [{"name": "accuracy", "value": 0.8, "tolerance": 0.01}], {"metrics": {"accuracy": 0.1}}
        )
    with pytest.raises(ValueError, match="finite captured"):
        maps.match_metrics(
            [{"name": "accuracy", "value": 0.8, "tolerance": 0.01}], {"metrics": {"accuracy": True}}
        )


async def test_arxiv_search_versions_link_to_one_identity(registry):
    current = "v1"

    def handler(request):
        return httpx.Response(
            200,
            text=f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2601.12345{current}</id><title>Fixture</title><summary>Fixture abstract</summary></entry></feed>',
        )

    research = ResearchTools(registry, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    query = {"query": "fixture", "limit": 1, "from_year": 2023, "to_year": 2026}
    try:
        first = (await research.search_arxiv(query))["papers"][0]
        current = "v2"
        research.arxiv_last_request = 0
        second = (await research.search_arxiv(query))["papers"][0]
        assert first["source_id"] != second["source_id"]
        assert first["paper_id"] == second["paper_id"]
        assert first["arxiv_version"] == "v1" and second["arxiv_version"] == "v2"
    finally:
        await research.close()
