from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Literal

import httpx
from pydantic import Field

from research_cli.document_parser import PARSER, parse_pdf_pages
from research_cli.research_map import PaperIdentity, canonical_arxiv, canonical_doi
from research_cli.storage import Store, encode, identifier
from research_cli.tools import Args, Empty, Registry, Workspace


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.extend(run[i : i + 2] for i in range(max(1, len(run) - 1)))
    return words


def bm25(query: str, documents: list[str]) -> list[float]:
    bags = [Counter(tokens(doc)) for doc in documents]
    n = len(bags)
    avg = sum(sum(b.values()) for b in bags) / max(n, 1) or 1
    scores = [0.0] * n
    for term in set(tokens(query)):
        df = sum(term in b for b in bags)
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for i, bag in enumerate(bags):
            tf = bag[term]
            scores[i] += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * sum(bag.values()) / avg))
    return scores


def cosine(a, b):
    if len(a) != len(b):
        raise ValueError("Embedding dimension mismatch")
    den = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / den if den else 0.0


def rrf(rankings: list[list[str]], k=60):
    scores = Counter()
    for ranking in rankings:
        for rank, key in enumerate(ranking, 1):
            scores[key] += 1 / (k + rank)
    return scores


def index_pages(
    store: Store, pages: list[str], title: str, provenance: dict, paper_id: str | None = None
) -> dict:
    raw = "\n".join(pages)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    identity = {k: v for k, v in provenance.items() if k != "retrieved_at"}
    sid = "doc_" + hashlib.sha256((digest + encode(identity)).encode()).hexdigest()[:16]
    existing = store.db.execute("SELECT body FROM sources WHERE id=?", (sid,)).fetchone()
    previous_paper_id = json.loads(existing[0]).get("paper_id") if existing else None
    if paper_id and previous_paper_id and paper_id != previous_paper_id:
        raise ValueError(
            "Document already belongs to another paper; identities cannot be silently merged"
        )
    paper_id = paper_id or previous_paper_id
    if paper_id:
        PaperIdentity(store).get(paper_id)
    source = {
        "source_id": sid,
        "title": title,
        "level": "full-text-extracted",
        "content_sha256": digest,
        "provenance": provenance,
        "pages": len(pages),
        "extraction_note": (
            "Local OCR enabled; recognized text may contain errors. Verify quotations against the original page; table/formula reconstruction is not guaranteed."
            if provenance.get("extraction", {}).get("ocr")
            else "Text extraction only; OCR disabled and table/formula reconstruction is not guaranteed."
        ),
    }
    rows = []
    for page_no, text in enumerate(pages, 1):
        for offset in range(0, len(text), 1600):
            chunk = text[offset : offset + 2000]
            if chunk.strip():
                rows.append(
                    (
                        f"{sid}_p{page_no}_{offset}",
                        sid,
                        encode({"page": page_no, "char_start": offset}),
                        chunk,
                    )
                )
    if not rows:
        raise ValueError(
            "No extractable text. For scanned PDFs, import with ocr=true and installed language data; recognition is not guaranteed."
        )
    store.put("sources", sid, source)
    if paper_id:
        PaperIdentity(store).attach(sid, paper_id)
        source["paper_id"] = paper_id
    with store.db:
        for row in rows:
            store.db.execute(
                "INSERT OR IGNORE INTO chunks(id,source,position,text) VALUES(?,?,?,?)", row
            )
    return {**source, "chunks": len(rows)}


class Query(Args):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=8, ge=1, le=30)


class PaperQuery(Query):
    from_year: int = Field(default_factory=lambda: date.today().year - 3, ge=1900, le=2200)
    to_year: int = Field(default_factory=lambda: date.today().year, ge=1900, le=2200)


class Import(Args):
    path: str
    ocr: bool = Field(
        default=False,
        description="Enable selective local Tesseract OCR for scanned PDF pages; requires installed verified language data and at most 20 pages.",
    )
    ocr_languages: list[Literal["eng", "chi_sim", "chi_tra"]] = Field(
        default_factory=lambda: ["eng"], min_length=1, max_length=3
    )
    tessdata_path: str | None = Field(
        default=None,
        description="Optional workspace-relative directory containing official pinned .traineddata files. Otherwise uses the trusted configured OCR cache.",
    )
    paper_id: str | None = Field(
        default=None,
        description="Existing canonical paper_id, explicitly linking this fulltext to its metadata; never guessed from its title.",
    )


class Arxiv(Args):
    arxiv_id: str = Field(pattern=r"^(\d{4}\.\d{4,5}|[a-zA-Z-]+/\d{7})(v\d+)?$")


class Repo(Args):
    repository: str = Field(description="owner/repo or https://github.com/owner/repo")


class RepoFile(Repo):
    path: str
    ref: str = Field(
        description="Pinned commit SHA from inspect_repository", pattern=r"^[a-fA-F0-9]{40}$"
    )


class Source(Args):
    source_id: str


class Chunk(Args):
    chunk_id: str


class Evidence(Args):
    chunk_id: str
    quote: str = Field(min_length=1, max_length=2000)
    claim: str = Field(min_length=1, max_length=2000)
    relation: str = Field(pattern=r"^(supports|contradicts|context|uncertain)$")


def repo_parts(value):
    value = value.removeprefix("https://github.com/").rstrip("/").removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("Expected GitHub owner/repository")
    return value


class ResearchTools:
    def __init__(self, registry: Registry, client=None):
        self.registry, self.store = registry, registry.store
        self.identities = PaperIdentity(self.store)
        self.ws = Workspace(self.store.workspace)
        self.client = client or httpx.AsyncClient(
            timeout=30,
            follow_redirects=False,
            headers={"User-Agent": "ResearchCLI/0.1 (research tool)"},
        )
        self.arxiv_lock = asyncio.Lock()
        self.arxiv_last_request = 0.0

    async def close(self):
        await self.client.aclose()

    async def github(self, endpoint, params=None):
        headers = {"Accept": "application/vnd.github+json"}
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
        response = await self.client.get(
            "https://api.github.com" + endpoint, params=params, headers=headers
        )
        response.raise_for_status()
        return response.json()

    async def search_papers(self, a):
        if a["from_year"] > a["to_year"]:
            raise ValueError("from_year must not exceed to_year")
        response = await self.client.get(
            "https://api.crossref.org/works",
            params={
                "query": a["query"],
                "rows": a["limit"],
                "filter": f"from-pub-date:{a['from_year']}-01-01,until-pub-date:{a['to_year']}-12-31",
            },
        )
        response.raise_for_status()
        results = []
        for item in response.json()["message"]["items"]:
            doi = item.get("DOI", "")
            if not doi:
                continue
            doi = canonical_doi(doi)
            abstract = re.sub(r"<[^>]+>", " ", item.get("abstract", "")).strip()
            sid = "doi_" + hashlib.sha256(doi.lower().encode()).hexdigest()[:16]
            paper = {
                "source_id": sid,
                "doi": doi,
                "url": item.get("URL"),
                "title": (item.get("title") or [""])[0],
                "authors": item.get("author", []),
                "published": item.get("published", {}),
                "abstract": abstract,
                "level": "abstract" if abstract else "metadata",
                "provider": "Crossref",
                "query": a,
                "retrieved_at": time.time(),
                "links": item.get("link", []),
            }
            self.store.put("sources", sid, paper)
            identity = self.identities.register(doi=doi, source_ids=[sid], title=paper["title"])
            paper["paper_id"] = identity["paper_id"]
            results.append(paper)
        return {
            "papers": results,
            "coverage": "Crossref only; code links and abstracts may be missing.",
        }

    async def search_arxiv(self, a):
        if a["from_year"] > a["to_year"]:
            raise ValueError("from_year must not exceed to_year")
        terms = re.findall(r"[\w-]+", a["query"])
        if not terms:
            raise ValueError("Query needs search terms")
        query = " AND ".join(f'all:"{term}"' for term in terms)
        query = f"({query}) AND submittedDate:[{a['from_year']}01010000 TO {a['to_year']}12312359]"
        async with self.arxiv_lock:
            await asyncio.sleep(max(0, 3 - (time.monotonic() - self.arxiv_last_request)))
            self.arxiv_last_request = time.monotonic()
            response = await self.client.get(
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": query,
                    "max_results": a["limit"],
                    "sortBy": "relevance",
                    "sortOrder": "descending",
                },
            )
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValueError("arXiv response exceeded 2 MB")
        root = ET.fromstring(response.content)
        atom = {"a": "http://www.w3.org/2005/Atom"}
        results = []
        for entry in root.findall("a:entry", atom):
            url = entry.findtext("a:id", "", atom)
            if "/abs/" not in url:
                raise ValueError("arXiv returned an error entry")
            arxiv_id = url.split("/abs/", 1)[1]
            arxiv_base_id, arxiv_version = canonical_arxiv(arxiv_id)
            arxiv_id = arxiv_base_id + (arxiv_version or "")
            sid = "arxiv_" + hashlib.sha256(arxiv_id.encode()).hexdigest()[:16]
            record = {
                "source_id": sid,
                "arxiv_id": arxiv_id,
                "arxiv_base_id": arxiv_base_id,
                "arxiv_version": arxiv_version,
                "title": " ".join(entry.findtext("a:title", "", atom).split()),
                "abstract": " ".join(entry.findtext("a:summary", "", atom).split()),
                "authors": [
                    author.findtext("a:name", "", atom)
                    for author in entry.findall("a:author", atom)
                ],
                "published": entry.findtext("a:published", "", atom),
                "url": url,
                "links": [link.attrib.get("href", "") for link in entry.findall("a:link", atom)],
                "level": "abstract",
                "provider": "arXiv",
                "query": a,
                "retrieved_at": time.time(),
            }
            self.store.put("sources", sid, record)
            identity = self.identities.register(
                arxiv_id=arxiv_id, source_ids=[sid], title=record["title"]
            )
            record["paper_id"] = identity["paper_id"]
            results.append(record)
        return {
            "papers": results,
            "coverage": "arXiv metadata and abstracts; not peer-review or code-authorship verification",
        }

    async def search_repositories(self, a):
        data = await self.github("/search/repositories", {"q": a["query"], "per_page": a["limit"]})
        return {
            "repositories": [
                {
                    "repository": r["full_name"],
                    "url": r["html_url"],
                    "description": r.get("description"),
                    "stars": r.get("stargazers_count"),
                    "license": r.get("license"),
                    "updated_at": r.get("updated_at"),
                }
                for r in data["items"]
            ],
            "incomplete_results": data.get("incomplete_results", False),
            "relationship": "Search candidates only. Verify paper association and pin a commit with inspect_repository.",
        }

    async def import_document(self, a):
        if a.get("paper_id"):
            self.identities.get(a["paper_id"])
        path = self.ws.path(a["path"])
        if not path.is_file() or path.stat().st_size > 20_000_000:
            raise ValueError("Document must be a regular file up to 20 MB")
        data = path.read_bytes()
        extraction = {}
        if path.suffix.lower() == ".pdf":
            tessdata = None
            if a.get("tessdata_path"):
                if not a.get("ocr", False):
                    raise ValueError("tessdata_path requires ocr=true")
                tessdata = self.ws.path(a["tessdata_path"])
                # Resolve each requested model as a workspace read; a model
                # symlink cannot grant the worker access outside the workspace.
                for language in a.get("ocr_languages", ["eng"]):
                    self.ws.path(
                        str((tessdata / f"{language}.traineddata").relative_to(self.ws.root))
                    )
            elif self.registry.settings.ocr_tessdata_path:
                # Settings are selected by the user, not by tool arguments.
                tessdata = Path(self.registry.settings.ocr_tessdata_path).expanduser().resolve()
            pages = await self.pdf_pages(
                data,
                ocr=a.get("ocr", False),
                languages=a.get("ocr_languages", ["eng"]),
                tessdata_path=tessdata,
                provenance=extraction,
            )
        else:
            if a.get("ocr") or a.get("tessdata_path"):
                raise ValueError("OCR import currently supports PDF files only")
            text = data.decode("utf-8")
            pages = [text]
        return index_pages(
            self.store,
            pages,
            path.name,
            {
                "path": str(path.relative_to(self.ws.root)),
                "file_sha256": hashlib.sha256(data).hexdigest(),
                **({"extraction": extraction} if path.suffix.lower() == ".pdf" else {}),
            },
            paper_id=a.get("paper_id"),
        )

    async def pdf_pages(self, data, **options):
        return await parse_pdf_pages(data, **options)

    async def download_arxiv(self, a):
        base_id, version = canonical_arxiv(a["arxiv_id"])
        arxiv_id = base_id + (version or "")
        identity = self.identities.register(arxiv_id=arxiv_id)
        url = "https://arxiv.org/pdf/" + arxiv_id
        data = bytearray()
        async with self.client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 20_000_000:
                    raise ValueError("PDF download exceeded 20 MB")
        if not data.startswith(b"%PDF"):
            raise ValueError("arXiv did not return a PDF; no text inferred")
        return index_pages(
            self.store,
            await self.pdf_pages(bytes(data)),
            a["arxiv_id"],
            {
                "url": url,
                "arxiv_id": arxiv_id,
                "requested_version": version
                or "latest; resolved version not independently verified",
                "file_sha256": hashlib.sha256(data).hexdigest(),
                "retrieved_at": time.time(),
                "extraction": PARSER.copy(),
            },
            paper_id=identity["paper_id"],
        )

    async def inspect_repository(self, a):
        repo = repo_parts(a["repository"])
        meta = await self.github(f"/repos/{repo}")
        branch = meta["default_branch"]
        commit = await self.github(f"/repos/{repo}/commits/{branch}")
        readme = ""
        try:
            data = await self.github(f"/repos/{repo}/readme", {"ref": commit["sha"]})
            readme = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
        record = {
            "repository": repo,
            "url": meta["html_url"],
            "description": meta.get("description"),
            "commit": commit["sha"],
            "default_branch": branch,
            "license": meta.get("license"),
            "archived": meta["archived"],
            "readme": readme,
            "paper_relationship": "unverified; match with paper-author evidence",
            "reproduction_status": "repository_inspected_only",
            "source_id": "github_"
            + hashlib.sha256((repo.lower() + commit["sha"]).encode()).hexdigest()[:16],
            "level": "repository_inspection",
            "provider": "GitHub",
            "retrieved_at": time.time(),
        }
        self.store.put("sources", record["source_id"], record)
        return record

    async def read_repository_file(self, a):
        repo = repo_parts(a["repository"])
        if ".." in a["path"].split("/") or a["path"].startswith("/"):
            raise ValueError("Expected repository-relative path")
        from urllib.parse import quote

        item = await self.github(
            f"/repos/{repo}/contents/{quote(a['path'], safe='/')}", {"ref": a["ref"]}
        )
        if isinstance(item, list):
            return {
                "entries": [{"path": x["path"], "type": x["type"]} for x in item[:200]],
                "commit": a["ref"],
            }
        if item.get("size", 0) > 1_000_000 or item.get("encoding") != "base64":
            raise ValueError("Remote file is too large or not available as inline content")
        text = base64.b64decode(item["content"]).decode("utf-8")
        record = {
            "repository": repo,
            "path": a["path"],
            "commit": a["ref"],
            "url": item["html_url"],
            "text": "\n".join(f"{i}: {line}" for i, line in enumerate(text.splitlines(), 1)),
            "source_id": "github_file_"
            + hashlib.sha256((repo.lower() + a["ref"] + a["path"]).encode()).hexdigest()[:20],
            "provider": "GitHub",
            "level": "repository_file",
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        self.store.put("sources", record["source_id"], record)
        return record

    async def find_code_links(self, a):
        source = self.store.get("sources", a["source_id"])
        rows = self.store.db.execute(
            "SELECT text FROM chunks WHERE source=?", (a["source_id"],)
        ).fetchall()
        text = encode(source) + "\n" + "\n".join(row[0] for row in rows)
        links = sorted(set(re.findall(r"https://github\.com/[\w.-]+/[\w.-]+", text)))
        return {
            "source_id": a["source_id"],
            "links": links,
            "relationship": "mentioned in available source; authorship and reproducibility not verified",
            "coverage": source.get("level", "unknown"),
        }

    async def search_library(self, a):
        rows = [dict(r) for r in self.store.db.execute("SELECT * FROM chunks ORDER BY id")]
        scores = bm25(a["query"], [r["text"] for r in rows])
        order = sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)
        return {
            "method": "bm25",
            "matches": [
                {
                    "chunk_id": rows[i]["id"],
                    "source_id": rows[i]["source"],
                    "position": json.loads(rows[i]["position"]),
                    "score": scores[i],
                    "text": rows[i]["text"],
                }
                for i in order[: a["limit"]]
                if scores[i] > 0
            ],
        }

    async def read_chunk(self, a):
        row = self.store.db.execute("SELECT * FROM chunks WHERE id=?", (a["chunk_id"],)).fetchone()
        if not row:
            raise ValueError("Unknown chunk")
        return {
            "chunk_id": row["id"],
            "source_id": row["source"],
            "position": json.loads(row["position"]),
            "text": row["text"],
        }

    async def save_evidence(self, a):
        chunk = await self.read_chunk(a)
        if a["quote"] not in chunk["text"]:
            raise ValueError("Quote must be an exact substring of the cited chunk")
        eid = identifier("ev")
        record = {
            "evidence_id": eid,
            **a,
            "source_id": chunk["source_id"],
            "position": chunk["position"],
            "quote_verified": True,
            "semantic_support": "not_independently_verified",
        }
        self.store.put("evidence", eid, record)
        return record

    async def list_evidence(self, a):
        return self.store.records("evidence")

    def register(self):
        r = self.registry
        r.add(
            "search_arxiv",
            "Search arXiv titles/abstracts with all query terms and a submission-year range. Prefer English terms; metadata only, not peer-review verification.",
            PaperQuery,
            self.search_arxiv,
            network=True,
        )
        r.add(
            "search_repositories",
            "Find candidate GitHub repositories by paper title or topic. Results do not establish author association or reproducibility.",
            Query,
            self.search_repositories,
            network=True,
        )
        r.add(
            "search_papers",
            "Search Crossref metadata in a year range. Not a full-text or exhaustive search.",
            PaperQuery,
            self.search_papers,
            network=True,
        )
        r.add(
            "import_document",
            "Index local UTF-8/PDF with source hash and page/chunk positions. Optional local OCR (20-page limit) requires verified language packs; recognized text must be checked against the original page.",
            Import,
            self.import_document,
        )
        r.add(
            "download_arxiv",
            "Retrieve an arXiv PDF by ID and index its text; max 20 MB/200 pages.",
            Arxiv,
            self.download_arxiv,
            network=True,
        )
        r.add(
            "inspect_repository",
            "Inspect a public GitHub repo, license and README at a pinned commit. Does not run code.",
            Repo,
            self.inspect_repository,
            network=True,
        )
        r.add(
            "read_repository_file",
            "Read a GitHub text file or list a directory at a pinned commit.",
            RepoFile,
            self.read_repository_file,
            network=True,
        )
        r.add(
            "find_code_links",
            "Find GitHub URLs explicitly mentioned in available source text, without guessing authorship.",
            Source,
            self.find_code_links,
        )
        r.add(
            "search_library",
            "BM25 search over locally indexed papers/notes. Use again with a revised query if evidence is weak.",
            Query,
            self.search_library,
        )
        r.add(
            "read_chunk",
            "Read the exact text and source position of an indexed chunk.",
            Chunk,
            self.read_chunk,
        )
        r.add(
            "save_evidence",
            "Link a claim to an exact source quote; verifies quotation but not scientific truth.",
            Evidence,
            self.save_evidence,
            "write",
        )
        r.add(
            "list_evidence",
            "List saved claim-to-source evidence and review status.",
            Empty,
            self.list_evidence,
        )
