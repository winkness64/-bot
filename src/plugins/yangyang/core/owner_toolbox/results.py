from __future__ import annotations

from typing import Any

from .types import OwnerToolboxLightResult, SlashCommand


def _truncate(text: str, limit: int) -> str:
    raw = str(text or "")
    if len(raw) <= limit:
        return raw
    return raw[:limit] + f"\n...[truncated {len(raw) - limit} chars]"


def _result(
    *,
    handled: bool = True,
    allowed: bool = True,
    reason: str,
    reply: str = "",
    tool_name: str | None = None,
    output: str = "",
    data: dict[str, Any] | None = None,
    slash_command: SlashCommand | None = None,
    raw_trace: list[dict[str, Any]] | None = None,
) -> OwnerToolboxLightResult:
    return OwnerToolboxLightResult(
        handled=handled,
        allowed=allowed,
        reason=reason,
        reply=reply,
        tool_name=tool_name,
        output=output,
        data=data,
        slash_command=slash_command,
        raw_trace=raw_trace,
    )
