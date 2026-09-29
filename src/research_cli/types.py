from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

Emit = Callable[[dict[str, Any]], Awaitable[None]]
Approve = Callable[[str, dict[str, Any]], Awaitable[bool]]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ModelReply:
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    native: list[dict] | None = None

    def message(self) -> dict:
        return {
            "role": "assistant",
            "content": self.text,
            "calls": [vars(call) for call in self.calls],
            "native": self.native,
        }


class AgentError(Exception):
    """A diagnosable runtime failure, safe to present without a traceback."""
