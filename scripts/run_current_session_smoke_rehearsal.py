from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "src/plugins/yangyang/data/runtime_config.json"
DEFAULT_COMMAND = "/yy-smoke-current 回应小维"
DEFAULT_SOURCE_MESSAGE_ID = "rehearsal-msg-1"
OWNER_UID = "335059272"
BOT_UID = "90001"
GROUP_ID = "31003"
XIAOWEI_UID = "3916107556"
DEFAULT_MODEL_REPLY = "收到，这句我来接。"


def _load_mock_pipeline_module():
    module_path = ROOT / "tests" / "mock_pipeline_test.py"
    spec = importlib.util.spec_from_file_location("mock_pipeline_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load mock pipeline helper: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("mock_pipeline_test", module)
    spec.loader.exec_module(module)
    return module


MOCK_PIPELINE = _load_mock_pipeline_module()


class MockBot:
    def __init__(self):
        self.calls: list[tuple[object, str]] = []

    async def send(self, event, message: str):
        self.calls.append((event, str(message or "")))
        return {"message_id": len(self.calls)}


class MockEvent:
    def __init__(self, *, user_id: str = OWNER_UID, group_id: str = GROUP_ID, message_id: str = DEFAULT_SOURCE_MESSAGE_ID):
        self.self_id = BOT_UID
        self.user_id = user_id
        self.group_id = group_id
        self.message_id = message_id
        self.raw_message = ""
        self.message = []


class SimpleConfig:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    def get(self, path: str, default: Any = None) -> Any:
        current: Any = self.data
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def get_bool(self, path: str, default: bool = False, env_key: str | None = None) -> bool:
        value = self.get(path, default)
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}


class TriggerMessage:
    def __init__(
        self,
        *,
        text: str,
        raw_content: str,
        msg_id: str,
        group_id: str = GROUP_ID,
        uid: str = OWNER_UID,
        is_owner: bool = True,
    ):
        self.channel = "group"
        self.uid = uid
        self.group_id = group_id
        self.msg_id = msg_id
        self.message_id = msg_id
        self.timestamp = 1710000000
        self.is_owner = is_owner
        self.text = text
        self.raw_content = raw_content
        self.bot_self_id = BOT_UID
        self.at_user_ids: list[str] = []
        self.reply_to_user_id: str | None = None
        self.reply_to_message_id: str | None = None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run current-session smoke rehearsal locally with mock bot/event only.",
    )
    parser.add_argument("--command", default=DEFAULT_COMMAND, help="Trigger command text. Default: /yy-smoke-current 回应小维")
    parser.add_argument("--mock-send", action="store_true", help="Run non-dry-run path with mock bot.send; still no real QQ/OneBot send")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to runtime_config.json")
    parser.add_argument("--source-message-id", default=DEFAULT_SOURCE_MESSAGE_ID, help="Mock source message id used for dedup rehearsal")
    reset_group = parser.add_mutually_exclusive_group()
    reset_group.add_argument("--reset-dedup", action="store_true", help="Reset in-memory safety dedup store before rehearsal (default)")
    reset_group.add_argument("--no-reset-dedup", action="store_true", help="Keep dedup store to observe duplicate blocking")
    return parser


def load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config root must be a JSON object")
    return raw


def build_recent_messages() -> list[dict[str, Any]]:
    return [
        {
            "message_id": "recent-0",
            "user_id": "10001",
            "uid": "10001",
            "nick": "路人甲",
            "text": "先别急，等小维说完",
            "content": "先别急，等小维说完",
            "timestamp": 1,
        },
        {
            "message_id": "recent-1",
            "user_id": XIAOWEI_UID,
            "uid": XIAOWEI_UID,
            "nick": "小维",
            "text": "这句我可能说重了，你看着回。",
            "content": "这句我可能说重了，你看着回。",
            "timestamp": 2,
        },
        {
            "message_id": "recent-2",
            "user_id": "10002",
            "uid": "10002",
            "nick": "路人乙",
            "text": "继续看后续。",
            "content": "继续看后续。",
            "timestamp": 3,
        },
    ]


def resolve_model_reply(command: str) -> str:
    inner = str(command or "")
    if "回应小维" in inner:
        return DEFAULT_MODEL_REPLY
    return inner.replace("/yy-smoke-current", "", 1).replace("/秧秧smoke", "", 1).strip() or DEFAULT_MODEL_REPLY


def build_trigger_message(command: str, source_message_id: str) -> TriggerMessage:
    return TriggerMessage(
        text=command,
        raw_content=command,
        msg_id=source_message_id,
        group_id=GROUP_ID,
        uid=OWNER_UID,
        is_owner=True,
    )


def make_config_proxy(config_data: dict[str, Any]) -> SimpleConfig:
    return SimpleConfig(config_data)


async def run_rehearsal(args: argparse.Namespace) -> int:
    mods = MOCK_PIPELINE.prepare_modules()
    config_path = Path(args.config)
    config_data = load_json_config(config_path)
    config = make_config_proxy(config_data)

    if not bool(args.no_reset_dedup):
        mods["reset_owner_action_delivery_safety_store"]()

    command = str(args.command or "")
    dry_run = not bool(args.mock_send)
    trigger_message = build_trigger_message(command, str(args.source_message_id or DEFAULT_SOURCE_MESSAGE_ID))
    trigger_message._current_session_smoke_recent_messages = build_recent_messages()
    trigger_message._current_session_smoke_model_reply = resolve_model_reply(command)

    bot = MockBot()
    event = MockEvent(message_id=trigger_message.msg_id)
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    result = await handle_trigger(trigger_message, config, bot=bot, event=event, dry_run=dry_run)

    print("[CURRENT_SESSION_SMOKE_REHEARSAL]")
    print(f"config_path={config_path}")
    print(f"command={command}")
    print(f"dry_run={str(dry_run).lower()}")
    print(f"mock_send={str(bool(args.mock_send)).lower()}")
    print(f"dedup_reset={str(not bool(args.no_reset_dedup)).lower()}")
    print(f"source_message_id={trigger_message.msg_id}")
    print(f"trigger_result.matched={str(bool(result.matched)).lower()}")
    print(f"trigger_result.enabled={str(bool(result.enabled)).lower()}")
    print(f"trigger_result.eligible={str(bool(result.eligible)).lower()}")
    print(f"trigger_result.attempted={str(bool(result.attempted)).lower()}")
    print(f"trigger_result.delivered={str(bool(result.delivered)).lower()}")
    print(f"trigger_result.real_send={str(bool(result.real_send)).lower()}")
    print(f"trigger_result.reason={result.reason}")
    print(f"trigger_result.inner_text={result.inner_text}")
    print(f"trigger_result.manual_smoke_reason={result.manual_smoke_reason}")
    print(f"trigger_result.audit_path={result.audit_path}")
    print(f"mock_send_count={len(bot.calls)}")
    if bot.calls:
        preview = bot.calls[-1][1].replace("\n", " ").replace("\r", " ").strip()
        if len(preview) > 120:
            preview = preview[:120] + "…"
        print(f"content_preview={preview}")
    print(
        "reminder=this_is_local_rehearsal_only; uses_mock_bot_event_only; does_not_connect_qq_or_onebot; "
        "does_not_send_real_messages; does_not_modify_config; cross_group_and_cross_session_stay_locked; "
        "real_smoke_still_requires_toggle_enable_ready_check_audit_tail_follow_and_current_session_prefixed_command"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run_rehearsal(args))
    except KeyboardInterrupt:
        print("error=keyboard_interrupt")
        return 1
    except Exception as exc:
        print(f"error={exc.__class__.__name__}:{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
