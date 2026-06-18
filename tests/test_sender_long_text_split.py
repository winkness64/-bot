from __future__ import annotations

import asyncio
from dataclasses import dataclass

from conftest import run
from mock_pipeline_runtime import DictConfig, prepare_modules  # type: ignore


@dataclass
class DummyDecision:
    reason: str = "unit_test"
    is_forced: bool = False
    reply_budget: int = 0


class DummyStore:
    def __init__(self):
        self.records: list[dict] = []

    def record_bot_message(self, **kwargs):
        self.records.append(kwargs)


class DummyCooldown:
    def __init__(self):
        self.calls: list[tuple[str, str, bool]] = []

    def record_reply(self, group_id, topic_hint: str = "", is_forced: bool = False):
        self.calls.append((group_id, topic_hint, is_forced))


class MockBot:
    def __init__(self):
        self.private_calls: list[tuple[int, str]] = []
        self.group_calls: list[tuple[int, str]] = []
        self.api_calls: list[tuple[str, dict]] = []
        self.self_id = 114514
        self.nickname = "秧秧"

    async def send_private_msg(self, user_id: int, message: str):
        self.private_calls.append((user_id, message))
        return {"message_id": len(self.private_calls)}

    async def send_group_msg(self, group_id: int, message: str):
        self.group_calls.append((group_id, message))
        return {"message_id": len(self.group_calls)}

    async def call_api(self, api: str, **kwargs):
        self.api_calls.append((api, kwargs))
        return {"message_id": len(self.api_calls)}


class FallbackMockBot(MockBot):
    async def call_api(self, api: str, **kwargs):
        raise RuntimeError("forward not supported")


@dataclass
class DummyMessage:
    channel: str
    uid: str = "335059272"
    group_id: str = "0"
    text: str = "长文测试"


def build_sender(Sender, bot, store, cooldown):
    cfg = DictConfig({"llm_streaming_progress_notice_enabled": False})
    return Sender(bot, store, cooldown, bot_uid="bot", config=cfg)


async def _test_private_long_text_forward_preferred(mods: dict) -> None:
    Sender = mods["Sender"]
    bot = MockBot()
    store = DummyStore()
    cooldown = DummyCooldown()
    sender = build_sender(Sender, bot, store, cooldown)

    long_text = "第一段：" + ("A" * 1300) + "\n第二段：" + ("B" * 950)
    msg = DummyMessage(channel="private")
    decision = DummyDecision()

    await sender.send(msg, decision, long_text, actual_tier="unit")

    assert len(bot.api_calls) == 1
    api, payload = bot.api_calls[0]
    assert api == "send_private_forward_msg"
    assert int(payload["user_id"]) == 335059272
    assert len(payload["messages"]) >= 2
    assert len(bot.private_calls) == 0
    assert len(store.records) == 1
    assert store.records[0]["text"] == long_text.strip()
    assert len(cooldown.calls) == 1
    print("[PASS] sender private long text forward preferred")


async def _test_private_long_text_fallback_split(mods: dict) -> None:
    Sender = mods["Sender"]
    bot = FallbackMockBot()
    store = DummyStore()
    cooldown = DummyCooldown()
    sender = build_sender(Sender, bot, store, cooldown)

    long_text = "第一段：" + ("A" * 1300) + "\n第二段：" + ("B" * 950)
    msg = DummyMessage(channel="private")
    decision = DummyDecision()

    await sender.send(msg, decision, long_text, actual_tier="unit")

    assert len(bot.private_calls) >= 2
    full = "\n".join(message for _, message in bot.private_calls)
    assert "第一段：" in full
    assert "第二段：" in full
    assert len(store.records) == 1
    assert store.records[0]["text"] == long_text.strip()
    assert len(cooldown.calls) == 1
    print("[PASS] sender private long text fallback split delivery")


async def _test_group_text_still_capped(mods: dict) -> None:
    Sender = mods["Sender"]
    bot = MockBot()
    store = DummyStore()
    cooldown = DummyCooldown()
    sender = build_sender(Sender, bot, store, cooldown)

    long_text = "G" * 1500
    msg = DummyMessage(channel="group", group_id="123456")
    decision = DummyDecision()

    await sender.send(msg, decision, long_text, actual_tier="unit")

    assert len(bot.group_calls) == 1
    sent = bot.group_calls[0][1]
    assert len(sent) == 1200
    assert len(store.records) == 1
    assert store.records[0]["text"] == sent
    print("[PASS] sender group text still capped")


def test_private_long_text_forward_preferred(mods: dict) -> None:
    run(_test_private_long_text_forward_preferred(mods))


def test_private_long_text_fallback_split(mods: dict) -> None:
    run(_test_private_long_text_fallback_split(mods))


def test_group_text_still_capped(mods: dict) -> None:
    run(_test_group_text_still_capped(mods))


async def main() -> None:
    mods = prepare_modules()
    await _test_private_long_text_forward_preferred(mods)
    await _test_private_long_text_fallback_split(mods)
    await _test_group_text_still_capped(mods)
    print("[OK] test_sender_long_text_split.py")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
