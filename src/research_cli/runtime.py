from __future__ import annotations

import asyncio
import hashlib
import time

from research_cli.context import Context
from research_cli.storage import Store, encode, identifier
from research_cli.tools import Registry, skill_catalog
from research_cli.types import AgentError, Approve, Emit


class Runtime:
    def __init__(self, store: Store, registry: Registry, provider, sid: str):
        self.store, self.registry, self.provider, self.sid = store, registry, provider, sid
        self.settings = registry.settings
        self.context = Context(store, sid, self.settings.context_chars)
        self._lock = asyncio.Lock()
        self.store.recover(sid)

    async def run(self, prompt: str, emit: Emit, approve: Approve):
        if self._lock.locked():
            raise AgentError("This session already has an active turn")
        async with self._lock:
            turn = identifier("t")
            started = time.monotonic()
            usage = {
                "input_tokens": 0,
                "output_tokens": 0,
                "unknown_calls": 0,
                "estimated_tokens": 0,
            }

            async def publish(event):
                if event["type"] == "text_delta":
                    await emit({"session_id": self.sid, "turn_id": turn, **event})
                else:
                    await emit(self.store.event(self.sid, turn, event))

            async def checked_approve(name, args):
                fingerprint = hashlib.sha256(
                    encode(
                        {"tool": name, "args": args, "workspace": str(self.store.workspace)}
                    ).encode()
                ).hexdigest()
                await publish(
                    {"type": "approval_requested", "tool": name, "fingerprint": fingerprint}
                )
                allowed = await approve(name, args)
                await publish(
                    {
                        "type": "approval_resolved",
                        "tool": name,
                        "fingerprint": fingerprint,
                        "approved": allowed,
                    }
                )
                return allowed

            self.store.message(self.sid, turn, {"role": "user", "content": prompt})
            await publish(
                {
                    "type": "turn_started",
                    "model": self.settings.model,
                    "api": self.settings.api,
                    "permission": self.settings.permission,
                }
            )
            status = "completed"
            try:
                await asyncio.wait_for(
                    self._loop(turn, usage, publish, checked_approve),
                    timeout=self.settings.max_turn_seconds,
                )
            except asyncio.CancelledError:
                status = "cancelled"
                self.store.recover(self.sid)
                await publish(
                    {
                        "type": "cancelled",
                        "detail": "Current turn stopped. Inspect /jobs for already-started experiments.",
                    }
                )
            except asyncio.TimeoutError:
                status = "timed_out"
                self.store.recover(self.sid)
                await publish({"type": "error", "detail": "Turn time budget exceeded"})
            except Exception as exc:
                status = "failed"
                self.store.recover(self.sid)
                detail = (
                    str(exc)
                    if isinstance(exc, (AgentError, ValueError))
                    else f"{type(exc).__name__}: model/tool request failed; inspect configuration or retry."
                )
                await publish({"type": "error", "detail": detail})
            finally:
                await publish(
                    {
                        "type": "turn_finished",
                        "status": status,
                        "usage": usage,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "estimated_cost": self._cost(usage),
                    }
                )
            return status

    def _cost(self, usage):
        s = self.settings
        if (
            s.input_price_per_million is None
            or s.output_price_per_million is None
            or usage["unknown_calls"]
        ):
            return None
        return (
            usage["input_tokens"] * s.input_price_per_million
            + usage["output_tokens"] * s.output_price_per_million
        ) / 1_000_000

    async def _loop(self, turn, usage, emit, approve):
        schemas = self.registry.schemas()
        for step in range(self.settings.max_steps):
            messages, system = self.context.build(schemas, skill_catalog())
            # A preflight estimate, not a tokenizer-independent hard billing guarantee.
            input_estimate = (len(encode(messages)) + len(system) + len(encode(schemas))) // 3 + 1
            used = usage["input_tokens"] + usage["output_tokens"] + usage["estimated_tokens"]
            available = self.settings.max_turn_tokens - used - input_estimate
            if available < 128:
                raise AgentError(
                    "Turn token budget reached (preflight estimate); no further model calls"
                )
            output_limit = min(self.settings.max_output_tokens, available)
            if self.settings.max_turn_cost is not None:
                cost = self._cost(usage)
                if cost is None:
                    raise AgentError("Cannot enforce configured cost budget with unknown usage")
                projected = (
                    cost
                    + (
                        input_estimate * self.settings.input_price_per_million
                        + output_limit * self.settings.output_price_per_million
                    )
                    / 1_000_000
                )
                if projected > self.settings.max_turn_cost:
                    raise AgentError("Configured cost budget would be exceeded by the next request")
            await emit(
                {
                    "type": "model_started",
                    "step": step + 1,
                    "estimated_input_tokens": input_estimate,
                }
            )
            reply = await self.provider.generate(messages, system, schemas, emit, output_limit)
            if reply.input_tokens is None or reply.output_tokens is None:
                usage["unknown_calls"] += 1
                usage["estimated_tokens"] += input_estimate + output_limit
            else:
                usage["input_tokens"] += reply.input_tokens
                usage["output_tokens"] += reply.output_tokens
            ids = [c.id for c in reply.calls]
            if len(set(ids)) != len(ids):
                raise AgentError("Duplicate tool call IDs; response rejected")
            self.store.message(self.sid, turn, reply.message())
            await emit(
                {
                    "type": "model_finished",
                    "input_tokens": reply.input_tokens,
                    "output_tokens": reply.output_tokens,
                    "tools": len(reply.calls),
                }
            )
            if not reply.calls:
                return
            for call in reply.calls:
                await emit(
                    {
                        "type": "tool_started",
                        "call_id": call.id,
                        "tool": call.name,
                        "arguments": call.arguments,
                    }
                )
                result = await self.registry.invoke(call.name, call.arguments, approve)
                self.store.message(
                    self.sid,
                    turn,
                    {
                        "role": "tool",
                        "call_id": call.id,
                        "name": call.name,
                        "content": encode(result),
                    },
                )
                await emit(
                    {
                        "type": "tool_finished",
                        "call_id": call.id,
                        "tool": call.name,
                        "result": result,
                    }
                )
                # Cancellation is checked between complete tool transactions.
                await asyncio.sleep(0)
        raise AgentError("Maximum model/tool rounds reached; progress was saved")
