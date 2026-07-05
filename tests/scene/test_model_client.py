from __future__ import annotations

import asyncio
from types import SimpleNamespace

from scenario.agent import (
    AnthropicModelClient,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    OpenAICompatibleModelClient,
)


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}'),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
        )


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.base_url = "https://openai-compatible.example/v1"
        self.chat = SimpleNamespace(completions=_FakeCompletions())


class _FakeReasoningCompletions:
    async def create(self, **kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        reasoning_content='{"ok": "from-reasoning"}',
                    ),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=5),
        )


class _FakeReasoningClient:
    def __init__(self) -> None:
        self.base_url = "https://api.longcat.chat/openai/v1"
        self.chat = SimpleNamespace(completions=_FakeReasoningCompletions())


def test_openai_compatible_model_client_normalizes_response() -> None:
    raw_client = _FakeOpenAIClient()
    client = OpenAICompatibleModelClient(raw_client, provider_kind="json_object_only")

    response = asyncio.run(
        client.complete(
            ModelRequest(
                model="demo-model",
                temperature=0.2,
                top_p=0.9,
                max_tokens=128,
                messages=[
                    ModelMessage(role="system", content="system"),
                    ModelMessage(role="user", content="user"),
                ],
                response_format={"type": "json_object"},
                presence_penalty=1.0,
                extra_body={"vendor": {"enabled": True}},
            )
        )
    )

    call = raw_client.chat.completions.calls[0]
    assert response == ModelResponse(
        text='{"ok": true}',
        usage=ModelUsage(input_tokens=11, output_tokens=7),
        raw=response.raw,
    )
    assert call["model"] == "demo-model"
    assert call["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {"vendor": {"enabled": True}}


def test_openai_compatible_model_client_reads_reasoning_content_fallback() -> None:
    client = OpenAICompatibleModelClient(_FakeReasoningClient())

    response = asyncio.run(
        client.complete(
            ModelRequest(
                model="LongCat-2.0",
                messages=[ModelMessage(role="user", content="return json")],
            )
        )
    )

    assert response.text == '{"ok": "from-reasoning"}'
    assert response.usage == ModelUsage(input_tokens=3, output_tokens=5)


def test_anthropic_model_client_builds_messages_payload_and_parses_response() -> None:
    client = AnthropicModelClient(
        api_key="key",
        base_url="https://anthropic.example/v1",
    )
    request = ModelRequest(
        model="claude-demo",
        temperature=0.1,
        top_p=0.8,
        max_tokens=256,
        messages=[
            ModelMessage(role="system", content="system rules"),
            ModelMessage(role="user", content="hello"),
        ],
        response_format={"type": "json_object"},
    )

    payload = client.build_payload(request)
    response = client.parse_response(
        {
            "content": [
                {"type": "text", "text": '{"answer":'},
                {"type": "text", "text": ' true}'},
            ],
            "usage": {"input_tokens": 13, "output_tokens": 5},
        }
    )

    assert client._messages_url() == "https://anthropic.example/v1/messages"
    assert payload["model"] == "claude-demo"
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert "system rules" in str(payload["system"])
    assert "valid JSON object" in str(payload["system"])
    assert payload["max_tokens"] == 256
    assert response.text == '{"answer": true}'
    assert response.usage == ModelUsage(input_tokens=13, output_tokens=5)
