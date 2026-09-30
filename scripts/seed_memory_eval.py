"""Seed explicitly synthetic project state identically for both memory ablation arms."""

import asyncio
import json
import sys
from pathlib import Path

from research_cli.config import Settings
from research_cli.mcp_server import Backend
from research_cli.memory import MemoryWrite
from research_cli.research import index_pages


async def seed(workspace, case):
    backend = Backend(workspace, Settings(permission="workspace-write"))
    try:
        source = index_pages(
            backend.store, [case["quote"]], "Synthetic evaluation fixture", {"fixture": case["id"]}
        )
        chunk = backend.store.db.execute(
            "SELECT id FROM chunks WHERE source=?", (source["source_id"],)
        ).fetchone()[0]
        ev = await backend.research.save_evidence(
            {
                "chunk_id": chunk,
                "quote": case["quote"],
                "claim": "Evaluation fixture statement",
                "relation": "context",
            }
        )
        await backend.memory.save(
            MemoryWrite(kind="constraint", text=case["constraint"], status="active").model_dump()
        )
        await backend.memory.save(
            MemoryWrite(
                kind="hypothesis",
                text=case["hypothesis"],
                status="proposed",
                evidence_ids=[ev["evidence_id"]],
            ).model_dump()
        )
        job_id = "job_fixture_" + case["id"]
        backend.store.put(
            "jobs",
            job_id,
            {
                "job_id": job_id,
                "status": "failed",
                "backend": "synthetic_fixture_not_executed",
                "argv": ["fixture"],
                "snapshot_sha256": "fixture-only",
                "exit_code": 1,
                "output": "Synthetic fixture; no real experiment was run.",
            },
        )
        await backend.memory.save(
            MemoryWrite(
                kind="negative_result",
                text="A synthetic baseline run failed; inspect it before considering a rerun.",
                status="observed",
                job_ids=[job_id],
            ).model_dump()
        )
        print(
            json.dumps(
                {
                    "source_id": source["source_id"],
                    "evidence_id": ev["evidence_id"],
                    "job_id": job_id,
                }
            )
        )
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(seed(Path(sys.argv[1]), json.loads(sys.stdin.read())))
