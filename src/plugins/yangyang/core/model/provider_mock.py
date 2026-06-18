from __future__ import annotations

import copy
from typing import Any

from .provider_base import ModelProvider, ProviderResponse


class MockProvider(ModelProvider):
    def __init__(
        self,
        *,
        response_text: str = "mock response",
        model_used: str = "mock-model",
        token_usage: dict[str, Any] | None = None,
        latency_ms: int = 1,
        available: bool = True,
        error: Exception | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        responses: list[ProviderResponse | dict[str, Any] | str] | None = None,
    ):
        self.response_text = response_text
        self.model_used = model_used
        self.token_usage = token_usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.latency_ms = latency_ms
        self._available = available
        self.error = error
        self.tool_calls = list(tool_calls or [])
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def is_available(self) -> bool:
        return self._available

    async def complete(
        self,
        *,
        tier: str,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.72,
        timeout: float = 30,
        session_id: str | None = None,
        request_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        stream: bool = False,
        stream_callback: Any = None,
    ) -> ProviderResponse:
        self.calls.append(
            {
                "tier": tier,
                "model": model,
                "messages": copy.deepcopy(messages),
                "temperature": temperature,
                "timeout": timeout,
                "session_id": session_id,
                "request_id": request_id,
                "tools": tools,
                "tool_choice": tool_choice,
                "stream": bool(stream),
            }
        )
        if self.error is not None:
            raise self.error
        if self.responses:
            return self._coerce_response(self.responses.pop(0), tier=tier, model=model)
        return ProviderResponse(
            content=self.response_text,
            model_used=self.model_used or model,
            token_usage=dict(self.token_usage),
            latency_ms=int(self.latency_ms),
            tier=tier,
            tool_calls=list(self.tool_calls),
        )

    def _coerce_response(self, item: ProviderResponse | dict[str, Any] | str, *, tier: str, model: str) -> ProviderResponse:
        if isinstance(item, ProviderResponse):
            return item
        if isinstance(item, str):
            return ProviderResponse(
                content=item,
                model_used=self.model_used or model,
                token_usage=dict(self.token_usage),
                latency_ms=int(self.latency_ms),
                tier=tier,
            )
        return ProviderResponse(
            content=str(item.get("content", self.response_text) or ""),
            model_used=str(item.get("model_used", self.model_used or model) or model),
            token_usage=dict(item.get("token_usage", self.token_usage) or {}),
            latency_ms=int(item.get("latency_ms", self.latency_ms) or 0),
            tier=str(item.get("tier", tier) or tier),
            tool_calls=list(item.get("tool_calls", []) or []),
        )
