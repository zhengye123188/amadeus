"""Numeric usage summaries. Missing prices stay unknown; estimates are not invoices."""

from __future__ import annotations

import json
import math

from research_cli.tools import Empty


def usage_summary(store):
    ledger = store.root / "usage.jsonl"
    totals = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
    records = unknown = invalid = 0
    cost = 0.0
    package_calls = []
    if ledger.exists():
        if ledger.is_symlink() or not ledger.is_file() or ledger.stat().st_size > 50_000_000:
            raise ValueError("Expected a regular usage ledger no larger than 50 MB")
        with ledger.open() as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if row.get("category") == "package-tool":
                        if (
                            not all(
                                isinstance(row.get(key), str) and 0 < len(row[key]) <= 512
                                for key in ("source", "tool", "session_id")
                            )
                            or row.get("estimated_cost_usd") is not None
                        ):
                            raise ValueError("Invalid package usage")
                        package_calls.append(
                            {
                                "type": "billable_tool_usage",
                                "provider": row["source"],
                                "tool": row["tool"],
                                "cost_usd": None,
                            }
                        )
                        continue
                    tokens = row["tokens"]
                    values = {key: tokens[key] for key in totals}
                    if any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or value < 0
                        or not math.isfinite(value)
                        for value in values.values()
                    ):
                        raise ValueError("Invalid tokens")
                    estimate = row.get("estimated_cost_usd")
                    if estimate is not None and (
                        isinstance(estimate, bool)
                        or not isinstance(estimate, (int, float))
                        or estimate < 0
                        or not math.isfinite(estimate)
                    ):
                        raise ValueError("Invalid cost")
                    records += 1
                    for key, value in values.items():
                        totals[key] += value
                    if estimate is None:
                        unknown += 1
                    else:
                        cost += estimate
                except (ValueError, KeyError, TypeError):
                    invalid += 1
    tools = package_calls
    for row in store.db.execute("SELECT body FROM events ORDER BY id"):
        event = json.loads(row[0])
        if event.get("type") == "billable_tool_usage":
            tools.append(event)
    return {
        "model": {
            "requests": records,
            "tokens": totals,
            "known_estimated_cost_usd": cost,
            "unknown_price_requests": unknown,
            "invalid_ledger_rows": invalid,
            "total_estimated_cost_usd": cost if not unknown and not invalid else None,
        },
        "external_tools": {
            "calls": len(tools),
            "usage": tools[-100:],
            "total_cost_usd": None if tools else 0,
            "notice": "Tool usage is separate from model tokens; service pricing is not configured.",
        },
        "notice": "Local usage estimates, not provider invoices. Ledger begins with this CLI version; prior sessions, unavailable usage and external MCP billing may be absent.",
    }


def register_usage(registry):
    async def summary(_args):
        return usage_summary(registry.store)

    registry.add(
        "usage_summary",
        "Read numeric model usage, known cost estimates and unknown-price counts; external paid tools are tracked separately.",
        Empty,
        summary,
    )
