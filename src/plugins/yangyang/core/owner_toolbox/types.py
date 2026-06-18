from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SlashCommand:
    token: str
    rest: str
    argv: tuple[str, ...]
    raw_text: str


@dataclass(frozen=True)
class OwnerToolboxLightResult:
    handled: bool
    allowed: bool
    reason: str
    reply: str = ""
    tool_name: str | None = None
    output: str = ""
    data: dict[str, Any] | None = None
    slash_command: SlashCommand | None = None
    raw_trace: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ToolInvocation:
    tool_name: str
    args: dict[str, Any]
    source: str
    raw_text: str


@dataclass(frozen=True)
class ToolLoopMaxStepsCommand:
    action: str
    value: int | None = None
    raw_text: str = ""
