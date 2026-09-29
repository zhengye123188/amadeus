import json

import httpx
import pytest
from openai import AsyncOpenAI

from research_cli.config import Settings
from research_cli.providers import OpenAIProvider, chat_input, response_input
from research_cli.types import AgentError


def sse(events):
    return "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"


def client_for(payload, requests):
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=payload)

    return AsyncOpenAI(
        api_key="test-only", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def discard(event):
    pass


@pytest.mark.parametrize("finish", ["tool_calls", None, "length"])
async def test_real_sdk_chat_stream_assembles_arguments_only_on_completion(finish):
    parts = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_a",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": '{"path":'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"arguments": '"README.md"}'}}]
                    },
                    "finish_reason": finish,
                }
            ]
        },
        {
            "choices": [],
            "usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
        },
    ]
    events = [
        {
            "id": "chat_test",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "test",
            **part,
        }
        for part in parts
    ]
    requests = []
    provider = OpenAIProvider(Settings(api="chat", model="test"), client_for(sse(events), requests))
    try:
        if finish == "tool_calls":
            reply = await provider.generate(
                [{"role": "user", "content": "read"}], "system", [], discard, 200
            )
            assert reply.calls[0].arguments == '{"path":"README.md"}'
            assert reply.calls[0].id == "call_a"
            assert reply.input_tokens == 30
        else:
            with pytest.raises(AgentError, match="Incomplete"):
                await provider.generate([], "system", [], discard, 200)
        assert requests[0]["stream"] is True
    finally:
        await provider.close()


async def test_real_sdk_responses_preserves_native_reasoning_and_usage():
    output = [
        {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [],
            "encrypted_content": "opaque-test-payload",
        },
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_b",
            "name": "list_files",
            "arguments": "{}",
            "status": "completed",
        },
    ]
    response = {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "test",
        "output": output,
        "usage": {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
    }
    events = [{"type": "response.completed", "sequence_number": 1, "response": response}]
    requests = []
    provider = OpenAIProvider(Settings(model="test"), client_for(sse(events), requests))
    try:
        reply = await provider.generate(
            [{"role": "user", "content": "files"}], "system", [], discard, 200
        )
        assert reply.calls[0].name == "list_files"
        assert reply.output_tokens == 20
        reconstructed = response_input(
            [reply.message(), {"role": "tool", "call_id": "call_b", "content": "{}"}]
        )
        assert reconstructed[0]["encrypted_content"] == "opaque-test-payload"
        assert reconstructed[-1]["type"] == "function_call_output"
        assert requests[0]["store"] is False
        assert requests[0]["include"] == ["reasoning.encrypted_content"]
    finally:
        await provider.close()


async def test_responses_dropped_stream_rejects_partial_function():
    payload = sse(
        [
            {
                "type": "response.function_call_arguments.delta",
                "delta": '{"path":',
                "sequence_number": 1,
                "item_id": "fc_1",
                "output_index": 0,
            }
        ]
    )
    provider = OpenAIProvider(Settings(model="test"), client_for(payload, []))
    try:
        with pytest.raises(AgentError, match="disconnected"):
            await provider.generate([], "", [], discard, 200)
    finally:
        await provider.close()


def test_chat_history_keeps_tool_identity_without_native_metadata():
    history = chat_input(
        [
            {
                "role": "assistant",
                "calls": [{"id": "c", "name": "read_file", "arguments": "{}"}],
                "native": [{"type": "reasoning"}],
            },
            {"role": "tool", "call_id": "c", "content": "result"},
        ],
        "system",
    )
    assert history[1]["tool_calls"][0]["id"] == history[2]["tool_call_id"]
    assert "native" not in history[1]
