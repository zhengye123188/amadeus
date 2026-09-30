"""Read-only companion queries for Pi hooks; never instantiate job owners or replay actions."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from research_cli.config import Settings
from research_cli.memory import ContextQuery, ProjectMemory
from research_cli.storage import Store, encode
from research_cli.tools import Registry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--action", choices=["context", "memory", "evidence", "jobs", "status"], default="context"
    )
    args = parser.parse_args()
    store = Store(args.workspace)
    try:
        memory = ProjectMemory(Registry(store, Settings()))
        if args.action == "context":
            query = ContextQuery.model_validate_json(sys.stdin.read(8000))
            output = asyncio.run(memory.context(query.model_dump()))
        elif args.action == "memory":
            output = asyncio.run(
                memory.listing({"include_retired": True, "limit": 100, "offset": 0})
            )
        elif args.action in {"evidence", "jobs"}:
            output = store.records(args.action)[-100:]
        else:
            output = asyncio.run(memory.status({}))
        print(encode(output))
    finally:
        store.close()


if __name__ == "__main__":
    main()
