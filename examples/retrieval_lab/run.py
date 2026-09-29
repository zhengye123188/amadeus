"""CPU-only, dependency-free experiment fixture. No model and no external data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import time
from collections import Counter
from pathlib import Path


def tokens(text):
    return re.findall(r"[a-z0-9_]+", text.lower())


def score(query, documents, method):
    query_tokens = set(tokens(query))
    bags = [Counter(tokens(d)) for d in documents]
    if method == "overlap":
        return [sum(term in bag for term in query_tokens) for bag in bags]
    avg = sum(sum(b.values()) for b in bags) / len(bags) or 1
    result = [0.0] * len(bags)
    for term in query_tokens:
        df = sum(term in bag for bag in bags)
        idf = math.log(1 + (len(bags) - df + 0.5) / (df + 0.5))
        for i, bag in enumerate(bags):
            tf = bag[term]
            result[i] += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * sum(bag.values()) / avg))
    return result


def evaluate(data, split, method):
    documents = data["documents"]
    cases = []
    started = time.perf_counter()
    for query in data["queries"]:
        if query["split"] != split:
            continue
        scores = score(query["query"], [d["text"] for d in documents], method)
        order = sorted(range(len(documents)), key=lambda i: (-scores[i], documents[i]["id"]))
        ranking = [documents[i]["id"] for i in order if scores[i] > 0]
        relevant = set(query["relevant"])
        first = next((i for i, key in enumerate(ranking[:10], 1) if key in relevant), None)
        cases.append(
            {
                "query_id": query["id"],
                "ranking": ranking[:10],
                "recall_at_3": len(set(ranking[:3]) & relevant) / len(relevant),
                "reciprocal_rank_at_10": 1 / first if first else 0,
            }
        )
    count = len(cases)
    if not count:
        raise ValueError("Empty split")
    return {
        "method": method,
        "split": split,
        "queries": count,
        "recall_at_3": sum(x["recall_at_3"] for x in cases) / count,
        "mrr_at_10": sum(x["reciprocal_rank_at_10"] for x in cases) / count,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--output", type=Path, default=Path("metrics.json"))
    args = parser.parse_args()
    path = Path(__file__).with_name("dataset.json")
    data = json.loads(path.read_text())
    result = {
        "kind": "synthetic-retrieval-smoke",
        "seed": 0,
        "deterministic": True,
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "api_cost": 0,
        "created_at_unix": time.time(),
        "limitations": "Original toy fixture; not a paper reproduction or evidence of general research ability. Timing is one run, not a benchmark.",
        "results": [evaluate(data, args.split, method) for method in ["overlap", "bm25"]],
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
