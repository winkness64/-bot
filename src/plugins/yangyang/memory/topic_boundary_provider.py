from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


AsyncTopicBoundaryModelCall = Callable[[list[dict[str, str]]], Awaitable[str]]


@dataclass(frozen=True)
class TopicBoundaryProviderConfig:
    """Config for adapting an async model router to topic-boundary model_call."""

    model_tier: str = "v4_flash"
    timeout_seconds: float = 8.0


def extract_text(result: Any) -> str:
    """Extract response text from common router/provider return shapes.

    Supported shapes:
    - plain ``str``
    - ``(text, actual_tier)`` / list-like first-item tuple used by current ModelRouter
    - object with ``.text``
    - object with ``.content``
    - dict with ``text`` / ``content`` / ``message``
    - fallback: ``str(result)``
    """

    if isinstance(result, str):
        return result

    if isinstance(result, (tuple, list)) and result:
        return extract_text(result[0])

    if isinstance(result, dict):
        for key in ("text", "content", "message"):
            if key in result:
                return str(result[key])
        return str(result)

    for attr in ("text", "content"):
        if hasattr(result, attr):
            return str(getattr(result, attr))

    return str(result)


def build_topic_boundary_model_call(
    router: Any,
    config: TopicBoundaryProviderConfig | None = None,
) -> AsyncTopicBoundaryModelCall:
    """Build B2-B1-A compatible async ``model_call(messages) -> str``.

    The current project ``ModelRouter.call`` signature is::

        await router.call(tier=..., messages=..., temperature=..., session_id=...)

    It has no per-call timeout argument, so this adapter applies
    ``TopicBoundaryProviderConfig.timeout_seconds`` with ``asyncio.wait_for``.
    Exceptions are intentionally not swallowed; the async resolver converts them
    to ``model_error`` at its own boundary.
    """

    cfg = config or TopicBoundaryProviderConfig()

    async def model_call(messages: list[dict[str, str]]) -> str:
        result = await asyncio.wait_for(
            router.call(tier=cfg.model_tier, messages=messages),
            timeout=float(cfg.timeout_seconds),
        )
        return extract_text(result)

    return model_call
