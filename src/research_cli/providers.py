from __future__ import annotations

import json
import os
import re
import uuid

from openai import AsyncOpenAI

from research_cli.config import Settings
from research_cli.types import AgentError, Emit, ModelReply, ToolCall


def response_input(messages: list[dict]) -> list[dict]:
    result = []
    for msg in messages:
        if msg["role"] == "tool":
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": msg["call_id"],
                    "output": msg["content"],
                }
            )
        elif msg["role"] == "assistant" and msg.get("native"):
            result.extend(msg["native"])
        else:
            if msg.get("content"):
                result.append({"role": msg["role"], "content": msg["content"]})
            for call in msg.get("calls", []):
                result.append(
                    {
                        "type": "function_call",
                        "call_id": call["id"],
                        "name": call["name"],
                        "arguments": call["arguments"],
                    }
                )
    return result


def chat_input(messages: list[dict], system: str) -> list[dict]:
    result = [{"role": "system", "content": system}]
    for msg in messages:
        item = {"role": msg["role"], "content": msg.get("content") or ""}
        if msg["role"] == "tool":
            item["tool_call_id"] = msg["call_id"]
        if msg.get("calls"):
            item["tool_calls"] = [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {"name": c["name"], "arguments": c["arguments"]},
                }
                for c in msg["calls"]
            ]
        result.append(item)
    return result


class OpenAIProvider:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        if client is None:
            key = os.environ.get(settings.api_key_env)
            if not key:
                raise AgentError(f"Set {settings.api_key_env} locally, or use --demo (no model).")
            if not settings.model:
                raise AgentError(
                    "Set RESEARCH_MODEL or pass --model with a model available to you."
                )
            client = AsyncOpenAI(api_key=key, base_url=settings.base_url, timeout=90, max_retries=1)
        self.client = client

    async def close(self):
        await self.client.close()

    async def generate(self, messages, system, tools, emit: Emit, max_output_tokens: int):
        if self.settings.api == "chat":
            return await self._chat(messages, system, tools, emit, max_output_tokens)
        stream = await self.client.responses.create(
            model=self.settings.model,
            instructions=system,
            input=response_input(messages),
            tools=[{"type": "function", **tool, "strict": False} for tool in tools],
            stream=True,
            store=False,
            include=["reasoning.encrypted_content"],
            max_output_tokens=max_output_tokens,
        )
        completed = None
        try:
            async for event in stream:
                if event.type == "response.output_text.delta":
                    await emit({"type": "text_delta", "text": event.delta})
                elif event.type == "response.completed":
                    completed = event.response
                elif event.type in {"error", "response.failed", "response.incomplete"}:
                    raise AgentError(
                        f"Model stream ended with {event.type}; no partial tools executed."
                    )
        finally:
            await stream.close()
        if completed is None:
            raise AgentError(
                "Model stream disconnected before completion; no partial tools executed."
            )
        output = [item.model_dump(mode="json", exclude_none=True) for item in completed.output]
        calls = [
            ToolCall(x["call_id"], x["name"], x["arguments"])
            for x in output
            if x["type"] == "function_call"
        ]
        usage = completed.usage
        return ModelReply(
            text=completed.output_text,
            calls=calls,
            native=output,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
        )

    async def _chat(self, messages, system, tools, emit, max_output_tokens):
        kwargs = {
            "model": self.settings.model,
            "messages": chat_input(messages, system),
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": max_output_tokens,
        }
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
        stream = await self.client.chat.completions.create(**kwargs)
        text, calls, finish, usage = "", {}, None, None
        try:
            async for chunk in stream:
                if chunk.usage:
                    usage = chunk.usage
                for choice in chunk.choices:
                    if choice.index != 0:
                        continue
                    if choice.delta.content:
                        text += choice.delta.content
                        await emit({"type": "text_delta", "text": choice.delta.content})
                    for part in choice.delta.tool_calls or []:
                        call = calls.setdefault(part.index, {"id": "", "name": "", "arguments": ""})
                        call["id"] += part.id or ""
                        if part.function:
                            call["name"] += part.function.name or ""
                            call["arguments"] += part.function.arguments or ""
                    if choice.finish_reason:
                        finish = choice.finish_reason
        finally:
            await stream.close()
        if finish not in {"stop", "tool_calls"}:
            raise AgentError(f"Incomplete model response ({finish}); no partial tools executed.")
        parsed = [ToolCall(**calls[k]) for k in sorted(calls)]
        if any(not c.id or not c.name for c in parsed):
            raise AgentError("Model returned an incomplete tool identity")
        return ModelReply(
            text=text,
            calls=parsed,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )


class DemoProvider:
    """Transparent deterministic UI/tool demo. Never presented as model inference."""

    async def close(self):
        pass

    async def generate(self, messages, system, tools, emit, max_output_tokens):
        last = messages[-1]
        if last["role"] == "tool":
            result = json.loads(last["content"])
            text = (
                "[DEMO · 无模型推理] 工具返回：\n"
                + json.dumps(result, ensure_ascii=False, indent=2)[:5000]
            )
            await emit({"type": "text_delta", "text": text})
            return ModelReply(text=text, input_tokens=0, output_tokens=0)
        prompt = last["content"]
        match = re.search(r"@([^\s]+)", prompt)
        if match:
            name, args = "read_file", {"path": match[1]}
        elif any(x in prompt.lower() for x in ["list", "files", "文件", "演示", "demo"]):
            name, args = "list_files", {"path": "."}
        elif prompt.lower().startswith("search "):
            name, args = "search_library", {"query": prompt[7:]}
        else:
            text = (
                "[DEMO · 无模型推理] 可输入“列出文件”、'读取 @README.md'、"
                "'search keyword'，或 /help。真实科研推理需要配置模型和 API key。"
            )
            await emit({"type": "text_delta", "text": text})
            return ModelReply(text=text, input_tokens=0, output_tokens=0)
        return ModelReply(
            calls=[ToolCall("demo_" + uuid.uuid4().hex[:10], name, json.dumps(args))],
            input_tokens=0,
            output_tokens=0,
        )
