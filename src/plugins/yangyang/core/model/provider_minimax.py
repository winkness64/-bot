from __future__ import annotations

from .provider_base import ModelProvider, ProviderResponse


class MiniMaxM2Provider(ModelProvider):
    def __init__(self, available: bool = False):
        self._available = bool(available)

    @property
    def provider_name(self) -> str:
        return "minimax"

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
    ) -> ProviderResponse:
        raise NotImplementedError("MiniMaxM2Provider is a placeholder in M1 and must not call real API")
