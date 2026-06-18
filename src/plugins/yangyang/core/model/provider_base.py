from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProviderResponse:
    content: str
    model_used: str
    token_usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    tier: str = ""
    # OpenAI-compatible tool calls.  Normalized shape is intentionally loose:
    # {"id": str, "type": "function", "name": str, "arguments": dict|str}
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class ModelProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    async def list_models(self, *, tier: str, timeout: float = 30) -> list[str]:
        """Return provider model ids for one runtime profile.

        Providers that do not support OpenAI-compatible /models may leave this
        unimplemented.  The return value must contain model identifiers only;
        no secret, token, key, or base_url may be exposed.
        """
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError
