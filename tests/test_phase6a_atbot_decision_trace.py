from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
PLUGIN_ROOT = SRC_ROOT / "plugins" / "yangyang"
BOT_SELF_ID = "3940223711"
OWNER_UID = "335059272"


def install_nonebot_stubs() -> None:
    nonebot_mod = types.ModuleType("nonebot")
    log_mod = types.ModuleType("nonebot.log")
    adapters_mod = types.ModuleType("nonebot.adapters")
    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")

    logger = logging.getLogger("phase6a_test")
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

    class GroupMessageEvent:  # pragma: no cover
        pass

    class PrivateMessageEvent:  # pragma: no cover
        pass

    log_mod.logger = logger
    v11_mod.GroupMessageEvent = GroupMessageEvent
    v11_mod.PrivateMessageEvent = PrivateMessageEvent

    sys.modules.setdefault("nonebot", nonebot_mod)
    sys.modules.setdefault("nonebot.log", log_mod)
    sys.modules.setdefault("nonebot.adapters", adapters_mod)
    sys.modules.setdefault("nonebot.adapters.onebot", onebot_mod)
    sys.modules.setdefault("nonebot.adapters.onebot.v11", v11_mod)


def ensure_package(name: str, path: Path) -> None:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules.setdefault(name, mod)


def load_module(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def prepare_modules():
    install_nonebot_stubs()
    ensure_package("plugins", SRC_ROOT / "plugins")
    ensure_package("plugins.yangyang", PLUGIN_ROOT)
    ensure_package("plugins.yangyang.core", PLUGIN_ROOT / "core")

    load_module("plugins.yangyang.core.owner_rules", PLUGIN_ROOT / "core" / "owner_rules.py")
    event_adapter_mod = load_module("plugins.yangyang.core.event_adapter", PLUGIN_ROOT / "core" / "event_adapter.py")
    decision_mod = load_module("plugins.yangyang.core.decision_engine", PLUGIN_ROOT / "core" / "decision_engine.py")
    return event_adapter_mod, decision_mod


class Seg:
    def __init__(self, seg_type: str, **data):
        self.type = seg_type
        self.data = data


class Sender:
    def __init__(self, nickname: str = "tester", card: str = ""):
        self.nickname = nickname
        self.card = card


class FakeEvent:
    def __init__(self, *, self_id: str, user_id: str, group_id: str, message, raw_message: str):
        self.self_id = self_id
        self.user_id = user_id
        self.group_id = group_id
        self.message_id = "msg-1"
        self.message = message
        self.raw_message = raw_message
        self.sender = Sender()
        self.reply = None
        self.time = 0


def test_decision_trace_loguru_format_static() -> None:
    source = (PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8")
    marker = "yangyang plugin: decision_trace"
    assert marker in source
    line = next(line for line in source.splitlines() if marker in line)
    assert "%s" not in line, "decision_trace logger still uses printf-style placeholders"
    assert "uid={}" in line
    assert "group_id={}" in line
    assert "channel={}" in line
    assert "bot_self_id={}" in line
    assert "text={}" in line
    assert "at_user_ids={}" in line
    assert "is_at_bot={}" in line
    assert "is_owner={}" in line
    assert "owner_command={}" in line
    assert "explicit_command={}" in line
    assert "should_reply={}" in line
    assert "reason={}" in line
    assert "is_forced={}" in line
    assert "model_tier={}" in line
    print("[PASS] decision_trace loguru format static check")


def test_raw_cq_at_bot_detected(EventAdapter):
    adapter = EventAdapter(owner_id=OWNER_UID, owner_uids=[OWNER_UID])
    event = FakeEvent(
        self_id=BOT_SELF_ID,
        user_id="123456",
        group_id="622162372",
        message=[Seg("text", text="你好")],
        raw_message=f"[CQ:at,qq={BOT_SELF_ID}] 你好",
    )
    assert adapter._extract_at(event, BOT_SELF_ID) is True
    print("[PASS] raw cq at bot detected")


def test_raw_cq_at_user_ids(EventAdapter):
    adapter = EventAdapter(owner_id=OWNER_UID, owner_uids=[OWNER_UID])
    event = FakeEvent(
        self_id=BOT_SELF_ID,
        user_id="123456",
        group_id="622162372",
        message=[Seg("text", text="你好")],
        raw_message=f"[CQ:at,qq={BOT_SELF_ID}] 你好",
    )
    assert adapter._extract_at_user_ids(event) == [BOT_SELF_ID]
    print("[PASS] raw cq at_user_ids extracted")


def test_at_all_not_specific_bot(EventAdapter):
    adapter = EventAdapter(owner_id=OWNER_UID, owner_uids=[OWNER_UID])
    event = FakeEvent(
        self_id=BOT_SELF_ID,
        user_id="123456",
        group_id="622162372",
        message=[Seg("text", text="大家好")],
        raw_message="[CQ:at,qq=all] 大家好",
    )
    assert adapter._extract_at(event, BOT_SELF_ID) is False
    assert adapter._extract_at_user_ids(event) == []
    print("[PASS] at all ignored as specific bot")


def test_decision_engine_at_bot(EventAdapter, DecisionEngine):
    adapter = EventAdapter(owner_id=OWNER_UID, owner_uids=[OWNER_UID])
    engine = DecisionEngine(store=None, skill_loader=None)
    event = FakeEvent(
        self_id=BOT_SELF_ID,
        user_id="123456",
        group_id="622162372",
        message=[Seg("text", text="你好")],
        raw_message=f"[CQ:at,qq={BOT_SELF_ID}] 你好",
    )
    msg = adapter.adapt_group_msg(event)
    decision = engine.decide(msg)
    assert msg.is_at_bot is True
    assert decision.should_reply is True
    assert decision.reason == "at_bot"
    print("[PASS] decision engine replies on at bot")


def test_owner_plain_text_still_silent(EventAdapter, DecisionEngine):
    adapter = EventAdapter(owner_id=OWNER_UID, owner_uids=[OWNER_UID])
    engine = DecisionEngine(store=None, skill_loader=None)
    event = FakeEvent(
        self_id=BOT_SELF_ID,
        user_id=OWNER_UID,
        group_id="622162372",
        message=[Seg("text", text="你好")],
        raw_message="你好",
    )
    msg = adapter.adapt_group_msg(event)
    decision = engine.decide(msg)
    assert msg.is_owner is True
    assert msg.is_at_bot is False
    assert msg.explicit_command is False
    assert decision.should_reply is False
    assert decision.reason == "default_silent"
    print("[PASS] owner plain text still default silent")


def main() -> None:
    test_decision_trace_loguru_format_static()
    event_adapter_mod, decision_mod = prepare_modules()
    EventAdapter = event_adapter_mod.EventAdapter
    DecisionEngine = decision_mod.DecisionEngine

    test_raw_cq_at_bot_detected(EventAdapter)
    test_raw_cq_at_user_ids(EventAdapter)
    test_at_all_not_specific_bot(EventAdapter)
    test_decision_engine_at_bot(EventAdapter, DecisionEngine)
    test_owner_plain_text_still_silent(EventAdapter, DecisionEngine)
    print("PASS")


if __name__ == "__main__":
    main()
