import json

from research_cli.usage import usage_summary


def test_unknown_model_or_tool_cost_never_becomes_free(store):
    records = [
        {
            "tokens": {"input": 10, "output": 2, "cacheRead": 0, "cacheWrite": 0},
            "estimated_cost_usd": 0.01,
        },
        {
            "tokens": {"input": 8, "output": 3, "cacheRead": 0, "cacheWrite": 0},
            "estimated_cost_usd": None,
        },
    ]
    (store.root / "usage.jsonl").write_text(
        "\n".join(json.dumps(row) for row in records) + "\nbroken-row\n"
    )
    store.event(
        "mcp",
        "embedding",
        {"type": "billable_tool_usage", "provider": "embedding", "tokens": 20, "cost_usd": None},
    )
    result = usage_summary(store)
    assert result["model"]["tokens"]["input"] == 18
    assert result["model"]["known_estimated_cost_usd"] == 0.01
    assert result["model"]["total_estimated_cost_usd"] is None
    assert result["model"]["unknown_price_requests"] == 1
    assert result["model"]["invalid_ledger_rows"] == 1
    assert result["external_tools"]["total_cost_usd"] is None
