"""Provider-neutral model request/response adapters for agents."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import aiohttp


@dataclass(frozen=True)
class ModelMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ModelRequest:
    model: str
    messages: list[ModelMessage]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    response_format: Mapping[str, object] | None = None
    presence_penalty: float | None = None
    extra_body: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ModelResponse:
    text: str
    usage: ModelUsage = field(default_factory=ModelUsage)
    raw: object | None = None


class ModelClient(Protocol):
    provider_kind: str

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Return one chat completion in provider-neutral form."""


class OpenAICompatibleModelClient:
    """Adapter for OpenAI Chat Completions compatible endpoints."""

    def __init__(
        self,
        raw_client: Any,
        *,
        provider_kind: str = "openai_compatible",
    ) -> None:
        self.raw_client = raw_client
        self.provider_kind = provider_kind
        self.base_url = str(getattr(raw_client, "base_url", "") or "")

    async def complete(self, request: ModelRequest) -> ModelResponse:
        kwargs: dict[str, object] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.top_p is not None:
            kwargs["top_p"] = request.top_p
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.response_format is not None:
            kwargs["response_format"] = dict(request.response_format)
        if request.presence_penalty is not None:
            kwargs["presence_penalty"] = request.presence_penalty
        if request.extra_body is not None:
            kwargs["extra_body"] = dict(request.extra_body)

        response = await self.raw_client.chat.completions.create(**kwargs)
        text = _extract_openai_message_text(response.choices[0].message)
        usage = getattr(response, "usage", None)
        return ModelResponse(
            text=text,
            usage=ModelUsage(
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            ),
            raw=response,
        )


def _extract_openai_message_text(message: Any) -> str:  # noqa: ANN401
    content = getattr(message, "content", None)
    if content:
        return str(content)
    return str(getattr(message, "reasoning_content", "") or "")


class AnthropicModelClient:
    """Adapter for Anthropic Messages API compatible endpoints."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        anthropic_version: str = "2023-06-01",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") or "https://api.anthropic.com"
        self.anthropic_version = anthropic_version
        self.provider_kind = "anthropic"

    async def complete(self, request: ModelRequest) -> ModelResponse:
        url = self._messages_url()
        payload = self.build_payload(request)
        headers = {
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                response_text = await response.text()
                if response.status >= 400:
                    raise RuntimeError(
                        f"Anthropic endpoint returned {response.status}: {response_text}"
                    )
                data = json.loads(response_text)
        return self.parse_response(data)

    def build_payload(self, request: ModelRequest) -> dict[str, object]:
        system_parts: list[str] = []
        messages: list[dict[str, str]] = []
        for message in request.messages:
            if message.role == "system":
                system_parts.append(message.content)
                continue
            role = "assistant" if message.role == "assistant" else "user"
            messages.append({"role": role, "content": message.content})

        if request.response_format is not None:
            system_parts.append(
                "Return only a valid JSON object. Do not wrap it in markdown."
            )

        payload: dict[str, object] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or 1024,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.extra_body is not None:
            payload.update(dict(request.extra_body))
        return payload

    def parse_response(self, data: Mapping[str, object]) -> ModelResponse:
        content = data.get("content")
        parts: list[str] = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, Mapping) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
        usage = data.get("usage")
        input_tokens = output_tokens = 0
        if isinstance(usage, Mapping):
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)
        return ModelResponse(
            text="".join(parts),
            usage=ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            raw=data,
        )

    def _messages_url(self) -> str:
        if self.base_url.endswith("/messages"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"


__all__ = [
    "AnthropicModelClient",
    "ModelClient",
    "ModelMessage",
    "ModelRequest",
    "ModelResponse",
    "ModelUsage",
    "OpenAICompatibleModelClient",
]
