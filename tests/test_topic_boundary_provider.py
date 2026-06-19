from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import pytest

from src.plugins.yangyang.memory.topic_boundary_provider import (
    TopicBoundaryProviderConfig,
    build_topic_boundary_model_call,
    extract_text,
)
from src.plugins.yangyang.memory.topic_boundary_resolver import resolve_topic_boundary_with_model_async


class FakeAsyncRouter:
    def __init__(self, result: Any = "ok", *, error: Exception | None = None, delay: float = 0.0):
        self.result = result
        self.error = error
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def call(
        self,
        *,
        tier: str,
        messages: list[dict[str, str]],
        temperature: float = 0.72,
        session_id: str | None = None,
    ) -> Any:
        self.calls.append(
            {
                "tier": tier,
                "messages": messages,
                "temperature": temperature,
                "session_id": session_id,
            }
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class TextResult:
    text: str


@dataclass
class ContentResult:
    content: str


def _record(msg_id: str, text: str, ts: float, *, is_bot: bool = False) -> dict[str, Any]:
    return {
        "msg_id": msg_id,
        "uid": "yangyang_bot" if is_bot else "335059272",
        "nick": "秧秧" if is_bot else "漂♂总",
        "group_id": "",
        "channel": "private",
        "text": text,
        "raw_content": text,
        "is_bot": is_bot,
        "created_at": ts,
    }


@pytest.mark.asyncio
async def test_fake_async_router_called_with_messages_and_plain_str_returned() -> None:
    messages = [{"role": "user", "content": "把刚才讨论记一下"}]
    router = FakeAsyncRouter("plain answer")

    model_call = build_topic_boundary_model_call(router)
    result = await model_call(messages)

    assert result == "plain answer"
    assert router.calls == [
        {
            "tier": "v4_flash",
            "messages": messages,
            "temperature": 0.72,
            "session_id": None,
        }
    ]


@pytest.mark.asyncio
async def test_adapter_passes_model_tier_and_enforces_timeout_without_router_timeout_kwarg() -> None:
    messages = [{"role": "user", "content": "slow"}]
    router = FakeAsyncRouter("late answer", delay=0.05)
    config = TopicBoundaryProviderConfig(model_tier="v4_pro", timeout_seconds=0.01)

    model_call = build_topic_boundary_model_call(router, config)
    with pytest.raises(asyncio.TimeoutError):
        await model_call(messages)

    assert len(router.calls) == 1
    assert router.calls[0]["tier"] == "v4_pro"
    assert router.calls[0]["messages"] == messages
    assert "timeout" not in router.calls[0]


@pytest.mark.asyncio
async def test_text_attribute_return_is_extracted() -> None:
    router = FakeAsyncRouter(TextResult(text="from text attr"))

    result = await build_topic_boundary_model_call(router)([{"role": "user", "content": "x"}])

    assert result == "from text attr"


@pytest.mark.asyncio
async def test_content_attribute_return_is_extracted() -> None:
    router = FakeAsyncRouter(ContentResult(content="from content attr"))

    result = await build_topic_boundary_model_call(router)([{"role": "user", "content": "x"}])

    assert result == "from content attr"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result_obj", "expected"),
    [
        ({"text": "dict text"}, "dict text"),
        ({"content": "dict content"}, "dict content"),
        ({"message": "dict message"}, "dict message"),
    ],
)
async def test_dict_text_content_message_returns_are_extracted(result_obj: dict[str, str], expected: str) -> None:
    router = FakeAsyncRouter(result_obj)

    result = await build_topic_boundary_model_call(router)([{"role": "user", "content": "x"}])

    assert result == expected


def test_current_model_router_tuple_shape_extracts_first_text_item() -> None:
    assert extract_text(("router text", "v4_flash")) == "router text"


@pytest.mark.asyncio
async def test_router_exception_is_not_swallowed_by_adapter() -> None:
    error = RuntimeError("router boom")
    router = FakeAsyncRouter(error=error)
    model_call = build_topic_boundary_model_call(router)

    with pytest.raises(RuntimeError) as exc_info:
        await model_call([{"role": "user", "content": "x"}])

    assert exc_info.value is error


@pytest.mark.asyncio
async def test_adapter_chains_with_async_topic_boundary_resolver_resolved() -> None:
    raw = json.dumps(
        {
            "ok": True,
            "status": "resolved",
            "payload": "B2-B1-B 只新增 async router adapter 与 fake router 测试",
            "confidence": 0.94,
            "start_msg_id": "m1",
            "end_msg_id": "m2",
            "used_msg_ids": ["m1", "m2"],
            "reason": "两条连续讨论 provider adapter 范围",
        },
        ensure_ascii=False,
    )
    router = FakeAsyncRouter(raw)
    model_call = build_topic_boundary_model_call(
        router,
        TopicBoundaryProviderConfig(model_tier="v4_flash", timeout_seconds=1.0),
    )
    records = [
        _record("m1", "M2.2-B2-B1-B 开始做 topic boundary provider adapter", 1.0),
        _record("m2", "只用 fake async router，不接真实 provider", 2.0),
    ]

    result = await resolve_topic_boundary_with_model_async("把刚才 adapter 讨论记一下", records, model_call)

    assert result.status == "resolved"
    assert result.payload == "B2-B1-B 只新增 async router adapter 与 fake router 测试"
    assert result.used_msg_ids == ("m1", "m2")
    assert result.context_range["resolver"] == "topic_boundary_resolver_v1_mockable"
    assert len(router.calls) == 1
    assert router.calls[0]["tier"] == "v4_flash"
    assert "把刚才 adapter 讨论记一下" in router.calls[0]["messages"][1]["content"]
