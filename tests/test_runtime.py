import asyncio
import json

import pytest
from conftest import approve, deny

from research_cli.context import Context
from research_cli.runtime import Runtime
from research_cli.tools import Empty
from research_cli.types import ModelReply, ToolCall


class ScriptedProvider:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.inputs = []

    async def generate(self, messages, system, schemas, emit, limit):
        self.inputs.append(messages)
        return next(self.replies)


async def collect(events, event):
    events.append(event)


async def test_dynamic_loop_corrects_invalid_arguments_and_saves_trace(registry):
    provider = ScriptedProvider(
        [
            ModelReply(calls=[ToolCall("bad", "list_files", '{"path":7}')]),
            ModelReply(calls=[ToolCall("good", "list_files", "{}")]),
            ModelReply(text="Files inspected", input_tokens=100, output_tokens=10),
        ]
    )
    sid = registry.store.create_session()
    runtime = Runtime(registry.store, registry, provider, sid)
    events = []
    assert await runtime.run("Inspect files", lambda e: collect(events, e), deny) == "completed"
    first_result = json.loads(provider.inputs[1][-1]["content"])
    assert first_result["error"] == "invalid_arguments"
    assert json.loads(provider.inputs[2][-1]["content"])["ok"]
    assert registry.store.messages(sid)[-1]["content"] == "Files inspected"
    assert events[-1]["estimated_cost"] is None
    assert events[-1]["usage"]["unknown_calls"] == 2
    assert len([e for e in registry.store.events(sid) if e["type"] == "tool_finished"]) == 2


async def test_cancel_does_not_execute_next_tool_and_recovery_does_not_replay(registry):
    started = asyncio.Event()
    side_effects = []

    async def slow(a):
        started.set()
        await asyncio.Event().wait()

    async def write(a):
        side_effects.append("called")

    registry.add("slow", "slow", Empty, slow)
    registry.add("write", "write", Empty, write, "write")
    provider = ScriptedProvider(
        [ModelReply(calls=[ToolCall("one", "slow", "{}"), ToolCall("two", "write", "{}")])]
    )
    sid = registry.store.create_session()
    runtime = Runtime(registry.store, registry, provider, sid)
    events = []
    task = asyncio.create_task(runtime.run("Try", lambda e: collect(events, e), approve))
    await started.wait()
    task.cancel()
    assert await task == "cancelled"
    assert not side_effects
    messages = registry.store.messages(sid)
    assert [m["call_id"] for m in messages if m["role"] == "tool"] == ["one", "two"]
    assert all(
        json.loads(m["content"])["error"] == "interrupted" for m in messages if m["role"] == "tool"
    )
    assert registry.store.recover(sid) == 0


async def test_approval_decision_is_bound_to_args(registry):
    p = ScriptedProvider(
        [
            ModelReply(calls=[ToolCall("c", "remember", '{"key":"constraint","text":"CPU only"}')]),
            ModelReply(text="Denied"),
        ]
    )
    sid = registry.store.create_session()
    rt = Runtime(registry.store, registry, p, sid)
    events = []
    await rt.run("Remember", lambda e: collect(events, e), deny)
    assert not registry.store.notes()
    request = next(e for e in events if e["type"] == "approval_requested")
    decision = next(e for e in events if e["type"] == "approval_resolved")
    assert request["fingerprint"] == decision["fingerprint"]
    assert decision["approved"] is False


@pytest.mark.parametrize("budget", ["max_steps", "max_turn_tokens", "max_turn_cost"])
async def test_budgets_stop_loop(registry, budget):
    if budget == "max_steps":
        registry.settings.max_steps = 1
    elif budget == "max_turn_tokens":
        registry.settings.max_turn_tokens = 1024
    else:
        registry.settings.max_turn_cost = 0.000001
        registry.settings.input_price_per_million = 1
        registry.settings.output_price_per_million = 1
    provider = ScriptedProvider([ModelReply(calls=[ToolCall("a", "list_files", "{}")])])
    sid = registry.store.create_session()
    rt = Runtime(registry.store, registry, provider, sid)
    events = []
    assert await rt.run("Try", lambda e: collect(events, e), deny) == "failed"
    assert events[-1]["status"] == "failed"
    if budget != "max_steps":
        assert not provider.inputs


def test_compaction_keeps_tool_pairs_and_pinned_constraints(store):
    sid = store.create_session()
    store.note("compute", "CPU only; no paid APIs")
    for i in range(5):
        store.message(sid, str(i), {"role": "user", "content": f"Question {i}"})
        store.message(
            sid, str(i), ModelReply(calls=[ToolCall(f"c{i}", "list_files", "{}")]).message()
        )
        store.message(sid, str(i), {"role": "tool", "call_id": f"c{i}", "content": "{}"})
        store.message(sid, str(i), ModelReply(text="Answer").message())
    context = Context(store, sid, 80000)
    result = context.compact()
    assert result["archived_messages"] == 12
    messages, system = context.build([], "")
    assert {m["turn"] for m in messages} == {"3", "4"}
    assert "CPU only; no paid APIs" in system
    archive = json.loads(store.read_artifact(result["artifact_id"])["text"])
    assert {m["turn"] for m in archive} == {"0", "1", "2"}


async def test_timeout_finishes_turn(registry):
    class SlowProvider:
        async def generate(self, *args):
            await asyncio.Event().wait()

    registry.settings.max_turn_seconds = 1
    rt = Runtime(registry.store, registry, SlowProvider(), registry.store.create_session())
    events = []
    assert await rt.run("Wait", lambda e: collect(events, e), deny) == "timed_out"


async def test_duplicate_call_ids_rejected_before_side_effects(registry):
    provider = ScriptedProvider(
        [ModelReply(calls=[ToolCall("c", "list_files", "{}"), ToolCall("c", "list_files", "{}")])]
    )
    rt = Runtime(registry.store, registry, provider, registry.store.create_session())
    events = []
    assert await rt.run("Try", lambda e: collect(events, e), deny) == "failed"
    assert not any(e["type"] == "tool_started" for e in events)
