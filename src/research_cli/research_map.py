"""Canonical paper identity, evidence-backed comparisons and reproduction records.

These are independent, user-directed tools rather than a prescribed workflow.
An exact citation establishes provenance, not semantic or scientific correctness.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from typing import Literal
from urllib.parse import unquote

from pydantic import Field, model_validator

from research_cli.storage import Store, encode, identifier
from research_cli.tools import Args, Registry


def canonical_doi(value: str) -> str:
    value = unquote(value.strip())
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    if not re.fullmatch(r"10\.\d{1,9}/\S+", value):
        raise ValueError("Expected a DOI or doi.org URL")
    return value.lower()


def canonical_arxiv(value: str) -> tuple[str, str | None]:
    value = unquote(value.strip())
    value = re.sub(
        r"^(?:https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/|arxiv:\s*)", "", value, flags=re.I
    )
    value = value.removesuffix(".pdf")
    match = re.fullmatch(r"(\d{4}\.\d{4,5}|[a-zA-Z-]+/\d{7})(v[1-9]\d*)?", value)
    if not match:
        raise ValueError("Expected an arXiv ID or arxiv.org URL")
    return match[1].lower(), match[2]


class PaperIdentity:
    def __init__(self, store: Store):
        self.store = store
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS paper_identities (
                id TEXT PRIMARY KEY, body TEXT NOT NULL, updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_aliases (
                alias TEXT PRIMARY KEY, paper_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_sources (
                source_id TEXT PRIMARY KEY, paper_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_maps (
                paper_id TEXT PRIMARY KEY, body TEXT NOT NULL, updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_map_revisions (
                paper_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(paper_id, revision)
            );
            CREATE TABLE IF NOT EXISTS reproduction_plans (
                id TEXT PRIMARY KEY, body TEXT NOT NULL, updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reproduction_revisions (
                id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(id, revision)
            );
        """)

    def get(self, paper_id: str) -> dict:
        row = self.store.db.execute(
            "SELECT body FROM paper_identities WHERE id=?", (paper_id,)
        ).fetchone()
        if not row:
            raise ValueError("Unknown paper identity")
        return json.loads(row[0])

    def resolve(self, *, paper_id=None, doi=None, arxiv_id=None) -> str:
        if paper_id:
            self.get(paper_id)
            return paper_id
        alias = "doi:" + canonical_doi(doi) if doi else "arxiv:" + canonical_arxiv(arxiv_id)[0]
        row = self.store.db.execute(
            "SELECT paper_id FROM paper_aliases WHERE alias=?", (alias,)
        ).fetchone()
        if not row:
            raise ValueError("Unknown DOI/arXiv identity; register or retrieve it first")
        return row[0]

    def attach(self, source_id: str, paper_id: str):
        self.get(paper_id)
        source = self.store.get("sources", source_id)
        current = self.store.db.execute(
            "SELECT paper_id FROM paper_sources WHERE source_id=?", (source_id,)
        ).fetchone()
        if current and current[0] != paper_id:
            raise ValueError(
                "Source already belongs to another paper; identities cannot be silently merged"
            )
        with self.store.db:
            self.store.db.execute(
                "INSERT OR IGNORE INTO paper_sources VALUES(?,?)", (source_id, paper_id)
            )
        self.store.put("sources", source_id, {**source, "paper_id": paper_id})

    def register(
        self,
        *,
        doi=None,
        arxiv_id=None,
        source_ids=(),
        title="",
        paper_id=None,
        expected_revision=None,
    ):
        aliases = []
        version = None
        if doi:
            aliases.append("doi:" + canonical_doi(doi))
        if arxiv_id:
            base, version = canonical_arxiv(arxiv_id)
            aliases.append("arxiv:" + base)
        if not aliases and not source_ids and not paper_id:
            raise ValueError("A paper requires a DOI, arXiv ID or existing source")
        owners = {
            row[0]
            for alias in aliases
            if (
                row := self.store.db.execute(
                    "SELECT paper_id FROM paper_aliases WHERE alias=?", (alias,)
                ).fetchone()
            )
        }
        sources = [self.store.get("sources", sid) for sid in source_ids]
        for source in sources:
            if source.get("provider") == "GitHub" or source.get("level") in {
                "repository_inspection",
                "repository_file",
            }:
                raise ValueError("Repository records cannot be paper sources")
            if source.get("paper_id"):
                owners.add(source["paper_id"])
            # Explicit metadata identifiers must agree; a title is never an identity key.
            if doi and source.get("doi") and canonical_doi(source["doi"]) != canonical_doi(doi):
                raise ValueError("Source DOI conflicts with supplied DOI")
            if (
                arxiv_id
                and source.get("arxiv_id")
                and canonical_arxiv(source["arxiv_id"])[0] != canonical_arxiv(arxiv_id)[0]
            ):
                raise ValueError("Source arXiv ID conflicts with supplied arXiv ID")
        if paper_id:
            self.get(paper_id)
            owners.add(paper_id)
        if len(owners) > 1:
            raise ValueError(
                "Identifiers belong to different papers; explicit conflicting identities are not merged"
            )
        pid = next(iter(owners), None)
        old = self.get(pid) if pid else None
        if old and expected_revision is not None and old["revision"] != expected_revision:
            raise ValueError("Paper revision conflict; read the current identity before updating")
        if not pid:
            stable = aliases[0] if aliases else "source:" + source_ids[0]
            pid = "paper_" + hashlib.sha256(stable.encode()).hexdigest()[:20]
        combined = sorted(set((old or {}).get("aliases", []) + aliases))
        versions = sorted(
            set((old or {}).get("arxiv_versions", []) + ([version] if version else []))
        )
        titles = list(
            dict.fromkeys(
                (old or {}).get("titles", []) + ([title.strip()] if title.strip() else [])
            )
        )
        body = {
            "paper_id": pid,
            "aliases": combined,
            "titles": titles,
            "arxiv_versions": versions,
            "revision": (old or {}).get("revision", 0) + 1,
            "updated": time.time(),
            "identity_basis": "explicit identifiers/source attachment; never title similarity",
        }
        with self.store.db:
            self.store.db.execute(
                "INSERT OR REPLACE INTO paper_identities VALUES(?,?,?)",
                (pid, encode(body), body["updated"]),
            )
            for alias in combined:
                self.store.db.execute(
                    "INSERT OR IGNORE INTO paper_aliases VALUES(?,?)", (alias, pid)
                )
        for sid in source_ids:
            self.attach(sid, pid)
        return body


class IdentityWrite(Args):
    doi: str | None = None
    arxiv_id: str | None = None
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    title: str = Field(default="", max_length=2000)
    paper_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def revision_required(self):
        if self.paper_id and self.expected_revision is None:
            raise ValueError("Updating paper_id requires expected_revision")
        return self


class IdentityRead(Args):
    paper_id: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None

    @model_validator(mode="after")
    def one_identity(self):
        if sum(x is not None for x in (self.paper_id, self.doi, self.arxiv_id)) != 1:
            raise ValueError("Supply exactly one paper_id, DOI or arXiv ID")
        return self


class Page(Args):
    limit: int = Field(default=30, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


MapField = Literal["question", "method", "assumptions", "dataset", "evaluation", "limitations"]


class MapEntry(Args):
    text: str = Field(min_length=1, max_length=2000)
    basis: Literal["reported", "inference", "unknown"] = "reported"
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def provenance(self):
        if self.basis == "reported" and not self.evidence_ids:
            raise ValueError(
                "Reported paper statements require exact-quote evidence; use inference/unknown for unsupported notes"
            )
        return self


class MapWrite(Args):
    paper_id: str
    fields: dict[MapField, list[MapEntry]] = Field(min_length=1, max_length=6)
    expected_revision: int = Field(
        default=0,
        ge=0,
        description="0 creates a map; otherwise must match its current revision. Replaces all fields.",
    )


class Comparison(Args):
    paper_ids: list[str] = Field(min_length=1, max_length=30)


class MapRead(Args):
    paper_id: str


class Export(Comparison):
    format: Literal["json", "markdown", "bibtex"] = "markdown"


class TargetMetric(Args):
    name: str = Field(min_length=1, max_length=100)
    value: float
    tolerance: float = Field(default=0, ge=0)
    direction: Literal["maximize", "minimize", "match"] = "match"
    evidence_ids: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def finite(self):
        if not math.isfinite(self.value) or not math.isfinite(self.tolerance):
            raise ValueError("Metric target and tolerance must be finite")
        return self


class ReproductionWrite(Args):
    paper_id: str
    repository_source_id: str
    commit: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    association_evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    code_source_ids: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="Stored read_repository_file source IDs at this commit. Baseline verification checks their exact bytes in the executed input snapshot.",
    )
    dependencies: list[str] = Field(default_factory=list, max_length=100)
    data: list[str] = Field(default_factory=list, max_length=100)
    dataset_id: str = Field(default="", max_length=200)
    split: str = Field(default="", max_length=200)
    protocol: str = Field(default="", max_length=2000)
    configuration: dict[str, str] = Field(default_factory=dict, max_length=100)
    hardware: str = Field(default="", max_length=2000)
    command: list[str] = Field(default_factory=list, max_length=100)
    targets: list[TargetMetric] = Field(default_factory=list, max_length=50)
    notes: str = Field(default="", max_length=4000)
    plan_id: str | None = None
    expected_revision: int = Field(default=0, ge=0)


class PlanRead(Args):
    plan_id: str


class Stage(PlanRead):
    expected_revision: int = Field(ge=1)
    stage: Literal[
        "drafted",
        "environment_ready",
        "smoke_passed",
        "baseline_completed",
        "metrics_matched",
        "blocked",
    ]
    job_id: str | None = None
    note: str = Field(min_length=1, max_length=2000)


class ResearchMap:
    def __init__(self, registry: Registry):
        self.registry, self.store = registry, registry.store
        self.identities = PaperIdentity(self.store)

    def evidence(self, ids, paper_id):
        result = []
        for eid in ids:
            evidence = self.store.get("evidence", eid)
            chunk = self.store.db.execute(
                "SELECT source,text FROM chunks WHERE id=?", (evidence.get("chunk_id"),)
            ).fetchone()
            source = self.store.get("sources", evidence["source_id"])
            if source.get("paper_id") != paper_id:
                raise ValueError("Evidence must belong to this canonical paper")
            if (
                not chunk
                or chunk[0] != evidence["source_id"]
                or not evidence.get("quote")
                or evidence["quote"] not in chunk[1]
            ):
                raise ValueError("Evidence quote must still match its recorded source chunk")
            result.append(evidence)
        return result

    async def register_identity(self, a):
        return self.identities.register(**a)

    async def identity(self, a):
        pid = self.identities.resolve(**a)
        return {
            **self.identities.get(pid),
            "sources": [
                self.store.get("sources", r[0])
                for r in self.store.db.execute(
                    "SELECT source_id FROM paper_sources WHERE paper_id=? ORDER BY source_id",
                    (pid,),
                )
            ],
        }

    async def papers(self, a):
        rows = self.store.db.execute(
            "SELECT body FROM paper_identities ORDER BY updated DESC,id LIMIT ? OFFSET ?",
            (a["limit"], a["offset"]),
        ).fetchall()
        return {
            "papers": [json.loads(r[0]) for r in rows],
            "total": self.store.db.execute("SELECT count(*) FROM paper_identities").fetchone()[0],
        }

    def current_map(self, pid):
        self.identities.get(pid)
        row = self.store.db.execute(
            "SELECT body FROM research_maps WHERE paper_id=?", (pid,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    async def save_map(self, a):
        old = self.current_map(a["paper_id"])
        if (old or {}).get("revision", 0) != a["expected_revision"]:
            raise ValueError(
                "Research map revision conflict; compare/read current map before replacing it"
            )
        for entries in a["fields"].values():
            for entry in entries:
                self.evidence(entry["evidence_ids"], a["paper_id"])
        body = {
            "paper_id": a["paper_id"],
            "fields": a["fields"],
            "revision": a["expected_revision"] + 1,
            "updated": time.time(),
            "verification": "Exact-quote provenance checked; interpretation and comparability require review.",
        }
        with self.store.db:
            self.store.db.execute(
                "INSERT OR REPLACE INTO research_maps VALUES(?,?,?)",
                (body["paper_id"], encode(body), body["updated"]),
            )
            self.store.db.execute(
                "INSERT INTO research_map_revisions VALUES(?,?,?)",
                (body["paper_id"], body["revision"], encode(body)),
            )
        return body

    async def compare(self, a):
        papers = [
            {"identity": self.identities.get(pid), "map": self.current_map(pid)}
            for pid in dict.fromkeys(a["paper_ids"])
        ]
        warnings = []
        for field in ("dataset", "evaluation"):
            values = {
                tuple(x["text"] for x in (p["map"] or {}).get("fields", {}).get(field, []))
                for p in papers
            }
            if len(values) > 1:
                warnings.append(
                    f"Different or missing {field} descriptions; numerical results must not be assumed comparable"
                )
        return {
            "papers": papers,
            "missing_fields": {
                p["identity"]["paper_id"]: [
                    f
                    for f in (
                        "question",
                        "method",
                        "assumptions",
                        "dataset",
                        "evaluation",
                        "limitations",
                    )
                    if not (p["map"] or {}).get("fields", {}).get(f)
                ]
                for p in papers
            },
            "warnings": warnings,
            "comparability": "not_independently_verified",
            "title_based_merging": False,
        }

    async def read_map(self, a):
        return {
            "map": self.current_map(a["paper_id"]),
            "history": [
                json.loads(r[0])
                for r in self.store.db.execute(
                    "SELECT body FROM research_map_revisions WHERE paper_id=? ORDER BY revision",
                    (a["paper_id"],),
                )
            ],
        }

    async def export(self, a):
        result = await self.compare(a)
        if a["format"] == "json":
            content = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
        elif a["format"] == "markdown":
            lines = [
                "# Research comparison",
                "",
                "Exact-quote provenance does not establish scientific correctness or cross-paper comparability.",
                "",
            ]
            for p in result["papers"]:
                identity = p["identity"]
                lines += [
                    "## " + ((identity["titles"] or [identity["paper_id"]])[0]),
                    "",
                    "Identity: " + identity["paper_id"],
                    "Aliases: " + ", ".join(identity["aliases"]),
                    "",
                ]
                for field, entries in (p["map"] or {}).get("fields", {}).items():
                    lines += ["### " + field, ""]
                    for entry in entries:
                        lines.append(
                            f"- [{entry['basis']}] {entry['text']} (evidence: {', '.join(entry['evidence_ids']) or 'none'})"
                        )
                lines += [""]
            lines += ["Warnings: " + "; ".join(result["warnings"])]
            content = "\n".join(lines)
        else:
            entries = []
            for p in result["papers"]:
                identity = p["identity"]
                sources = [
                    self.store.get("sources", r[0])
                    for r in self.store.db.execute(
                        "SELECT source_id FROM paper_sources WHERE paper_id=? ORDER BY source_id",
                        (identity["paper_id"],),
                    )
                ]
                source = next(
                    (s for s in sources if s.get("provider") == "Crossref"),
                    next((s for s in sources if s.get("provider") == "arXiv"), {}),
                )

                # BibTeX escaping preserves data without allowing field syntax injection.
                def escaped(value):
                    escapes = {
                        "\\": "\\textbackslash{}",
                        "{": "\\{",
                        "}": "\\}",
                        "\n": " ",
                        "%": "\\%",
                        "&": "\\&",
                        "#": "\\#",
                        "_": "\\_",
                    }
                    return "".join(escapes.get(char, char) for char in str(value))

                fields = {
                    "title": source.get("title")
                    or (identity["titles"] or [identity["paper_id"]])[0]
                }
                authors = source.get("authors", [])
                if authors:
                    fields["author"] = " and ".join(
                        (x.get("family", "") + ", " + x.get("given", "")).strip(", ")
                        if isinstance(x, dict)
                        else str(x)
                        for x in authors
                    )
                for alias in identity["aliases"]:
                    if alias.startswith("doi:"):
                        fields["doi"] = alias[4:]
                    elif alias.startswith("arxiv:"):
                        fields["eprint"], fields["archivePrefix"] = alias[6:], "arXiv"
                published = source.get("published")
                if isinstance(published, dict) and published.get("date-parts"):
                    fields["year"] = published["date-parts"][0][0]
                elif isinstance(published, str) and re.match(r"\d{4}", published):
                    fields["year"] = published[:4]
                entries.append(
                    "@misc{"
                    + identity["paper_id"]
                    + ",\n"
                    + ",\n".join(
                        "  " + key + " = {" + escaped(value) + "}" for key, value in fields.items()
                    )
                    + "\n}"
                )
            content = "\n\n".join(entries)
        return {
            **self.store.artifact(content),
            "format": a["format"],
            "content": content,
            "metadata_note": "Only stored metadata exported; missing citation fields are not invented.",
        }

    def plan(self, pid):
        row = self.store.db.execute(
            "SELECT body FROM reproduction_plans WHERE id=?", (pid,)
        ).fetchone()
        if not row:
            raise ValueError("Unknown reproduction plan")
        return json.loads(row[0])

    def persist_plan(self, body):
        with self.store.db:
            self.store.db.execute(
                "INSERT OR REPLACE INTO reproduction_plans VALUES(?,?,?)",
                (body["plan_id"], encode(body), body["updated"]),
            )
            self.store.db.execute(
                "INSERT INTO reproduction_revisions VALUES(?,?,?)",
                (body["plan_id"], body["revision"], encode(body)),
            )

    async def save_plan(self, a):
        self.identities.get(a["paper_id"])
        repo = self.store.get("sources", a["repository_source_id"])
        if (
            repo.get("provider") != "GitHub"
            or repo.get("level") != "repository_inspection"
            or repo.get("commit", "").lower() != a["commit"].lower()
        ):
            raise ValueError("Commit must match an actual stored GitHub repository inspection")
        evidence = self.evidence(a["association_evidence_ids"], a["paper_id"])
        repo_name = repo["repository"].lower()
        mentions = any(
            repo_name
            in {
                r.lower().removesuffix(".git")
                for r in re.findall(r"https://github\.com/([\w.-]+/[\w.-]+)", ev["quote"])
            }
            for ev in evidence
        )
        if evidence and not mentions:
            raise ValueError("Association evidence does not mention the inspected repository")
        for metric in a["targets"]:
            self.evidence(metric["evidence_ids"], a["paper_id"])
        for sid in a["code_source_ids"]:
            code = self.store.get("sources", sid)
            if (
                code.get("level") != "repository_file"
                or code.get("repository", "").lower() != repo_name
                or code.get("commit", "").lower() != a["commit"].lower()
            ):
                raise ValueError(
                    "Code sources must be retrieved files from this pinned repository commit"
                )
        old = self.plan(a["plan_id"]) if a.get("plan_id") else None
        if (old or {}).get("revision", 0) != a["expected_revision"]:
            raise ValueError("Reproduction plan revision conflict")
        # Changed plans invalidate previous execution claims instead of inheriting readiness.
        body = {
            **{k: v for k, v in a.items() if k not in {"expected_revision", "plan_id"}},
            "plan_id": a.get("plan_id") or identifier("repro"),
            "revision": a["expected_revision"] + 1,
            "stage": "drafted",
            "updated": time.time(),
            "repository": repo["repository"],
            "relationship": "mentioned_in_paper; authorship_unverified"
            if mentions
            else "candidate; association_unverified",
            "stage_evidence": [],
            "readiness_gaps": [
                key
                for key in (
                    "dependencies",
                    "data",
                    "dataset_id",
                    "split",
                    "protocol",
                    "configuration",
                    "hardware",
                    "command",
                    "targets",
                    "code_source_ids",
                )
                if not a[key]
            ],
        }
        self.persist_plan(body)
        return body

    async def read_plan(self, a):
        return {
            **self.plan(a["plan_id"]),
            "history": [
                json.loads(r[0])
                for r in self.store.db.execute(
                    "SELECT body FROM reproduction_revisions WHERE id=? ORDER BY revision",
                    (a["plan_id"],),
                )
            ],
        }

    async def plans(self, a):
        rows = self.store.db.execute(
            "SELECT body FROM reproduction_plans ORDER BY updated DESC,id LIMIT ? OFFSET ?",
            (a["limit"], a["offset"]),
        ).fetchall()
        return {
            "plans": [json.loads(r[0]) for r in rows],
            "total": self.store.db.execute("SELECT count(*) FROM reproduction_plans").fetchone()[0],
        }

    async def stage(self, a):
        old = self.plan(a["plan_id"])
        if old["revision"] != a["expected_revision"]:
            raise ValueError("Reproduction plan revision conflict")
        stage = a["stage"]
        if stage in {"environment_ready", "smoke_passed", "baseline_completed", "metrics_matched"}:
            missing = [
                k
                for k in ("dependencies", "data", "configuration", "hardware", "command")
                if not old[k]
            ]
            if missing:
                raise ValueError("Readiness details missing: " + ", ".join(missing))
        evidence = {
            "stage": stage,
            "note": a["note"],
            "job_id": a["job_id"],
            "verification": "user-declared readiness",
        }
        if stage in {"smoke_passed", "baseline_completed", "metrics_matched"}:
            if not a["job_id"]:
                raise ValueError("This stage requires a completed recorded job")
            job = self.store.get("jobs", a["job_id"])
            if job.get("status") != "completed":
                raise ValueError(
                    "Failed, pending or interrupted jobs do not establish reproduction success"
                )
            if stage == "smoke_passed":
                evidence["verification"] = "completed job; scientific reproduction not established"
            else:
                # Import lazily: identity/map tools work without the optional experiment runner.
                from research_cli.experiments import verify_experiment

                captured = verify_experiment(self.store, job)
                if not old["targets"]:
                    raise ValueError(
                        "Baseline stages require target metrics grounded in paper evidence"
                    )
                self.validate_baseline(old, job, captured)
                evidence["metrics"] = captured
                evidence["verification"] = (
                    "completed run with verified metric artifact; scientific interpretation unverified"
                )
                if stage == "metrics_matched":
                    self.match_metrics(old["targets"], captured)
        body = {
            **old,
            "stage": stage,
            "revision": old["revision"] + 1,
            "updated": time.time(),
            "stage_evidence": old["stage_evidence"] + [evidence],
        }
        self.persist_plan(body)
        return body

    def validate_baseline(self, plan, job, captured):
        if job.get("argv") != plan["command"]:
            raise ValueError("Recorded experiment command differs from the reproduction plan")
        if not all(plan[k] for k in ("dataset_id", "split", "protocol", "code_source_ids")):
            raise ValueError("Baseline requires dataset/split/protocol and pinned code sources")
        dataset = captured.get("dataset", {})
        for key in ("dataset_id", "split", "protocol"):
            if dataset.get(key) != plan[key]:
                raise ValueError("Experiment dataset/protocol differs from plan: " + key)
        folder = self.store.root / "jobs" / job["job_id"]
        manifest_path = folder / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("Experiment input manifest is missing")
        manifest = json.loads(manifest_path.read_text())
        if hashlib.sha256(encode(manifest).encode()).hexdigest() != job.get("snapshot_sha256"):
            raise ValueError("Experiment input manifest hash changed")
        for sid in plan["code_source_ids"]:
            source = self.store.get("sources", sid)
            if manifest.get(source["path"]) != source["content_sha256"]:
                raise ValueError(
                    "Executed code does not match the retrieved pinned repository file: "
                    + source["path"]
                )
        for target in plan["targets"]:
            if target["name"] not in captured.get("metrics", {}):
                raise ValueError("Target metric missing from verified results: " + target["name"])

    @staticmethod
    def match_metrics(targets, captured):
        metrics = captured.get("metrics", {})
        for target in targets:
            metric = metrics.get(target["name"])
            value = metric.get("value") if isinstance(metric, dict) else metric
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
            ):
                raise ValueError("Missing finite captured metric: " + target["name"])
            matches = abs(value - target["value"]) <= target["tolerance"]
            if not matches:
                raise ValueError(
                    "Captured metric does not match declared target/tolerance: " + target["name"]
                )

    def register(self):
        for name, description, model, handler, effect in [
            (
                "register_paper_identity",
                "Register explicit DOI/arXiv/source identity; versions share a paper, titles never trigger merging. Conflicting papers are rejected.",
                IdentityWrite,
                self.register_identity,
                "write",
            ),
            (
                "get_paper_identity",
                "Read canonical paper aliases and attached metadata/fulltext sources.",
                IdentityRead,
                self.identity,
                "read",
            ),
            (
                "list_papers",
                "List canonical paper identities with pagination.",
                Page,
                self.papers,
                "read",
            ),
            (
                "save_research_map",
                "Save a revision-checked paper comparison map. Reported statements require exact-quote evidence belonging to this paper; inference is explicit.",
                MapWrite,
                self.save_map,
                "write",
            ),
            (
                "compare_papers",
                "Read structured paper maps, missing dimensions and dataset/protocol comparability warnings; no automatic scientific judgment.",
                Comparison,
                self.compare,
                "read",
            ),
            (
                "read_research_map",
                "Read a paper research map and its revision history.",
                MapRead,
                self.read_map,
                "read",
            ),
            (
                "export_research_map",
                "Export stored paper maps/citations as a JSON, Markdown or BibTeX artifact; missing metadata is never fabricated.",
                Export,
                self.export,
                "write",
            ),
            (
                "save_reproduction_plan",
                "Record a pinned repository, dependencies/data/config/hardware/commands and evidence-grounded targets; repository mentions never imply official authorship. Updating resets execution claims.",
                ReproductionWrite,
                self.save_plan,
                "write",
            ),
            (
                "read_reproduction_plan",
                "Read a reproduction checklist and revision history.",
                PlanRead,
                self.read_plan,
                "read",
            ),
            (
                "list_reproduction_plans",
                "List reproduction plans with pagination.",
                Page,
                self.plans,
                "read",
            ),
            (
                "update_reproduction_stage",
                "Update a reproduction record with revision guards; successful baseline stages require a completed job and verified metric artifacts. No steps are automatically executed.",
                Stage,
                self.stage,
                "write",
            ),
        ]:
            self.registry.add(name, description, model, handler, effect)
