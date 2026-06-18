from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULTS: dict[str, Any] = {
    "owner_action_manual_smoke_enabled": False,
    "owner_action_manual_smoke_owner_only": True,
    "owner_action_nonebot_sender_enabled": False,
    "owner_action_execution_enabled": False,
    "owner_action_allow_reply_current": False,
    "owner_action_current_session_delivery_enabled": False,
    "owner_action_delivery_dedup_ttl_seconds": 300,
    "owner_action_delivery_audit_path": "logs/owner_action_delivery_audit.jsonl",
}


def load_config(path: Path | None) -> dict[str, Any]:
    data = dict(DEFAULTS)
    if path is None or not path.exists():
        return data
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return data
    if isinstance(raw, dict):
        data.update(raw)
    return data


def resolve_audit_path(raw_path: str) -> str:
    path = Path(str(raw_path or DEFAULTS["owner_action_delivery_audit_path"]))
    if path.is_absolute():
        return str(path)
    return str(Path.cwd() / path)


def is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check current-session manual smoke readiness.")
    parser.add_argument("--config", help="Path to runtime_config.json", default="src/plugins/yangyang/data/runtime_config.json")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else None
    data = load_config(config_path)

    manual_smoke_enabled = is_true(data.get("owner_action_manual_smoke_enabled"))
    owner_only = is_true(data.get("owner_action_manual_smoke_owner_only", True))
    sender_enabled = is_true(data.get("owner_action_nonebot_sender_enabled"))
    execution_enabled = is_true(data.get("owner_action_execution_enabled"))
    allow_reply_current = is_true(data.get("owner_action_allow_reply_current"))
    current_session_enabled = is_true(data.get("owner_action_current_session_delivery_enabled"))
    dedup_ttl = int(data.get("owner_action_delivery_dedup_ttl_seconds", 300) or 300)
    audit_path = resolve_audit_path(str(data.get("owner_action_delivery_audit_path", DEFAULTS["owner_action_delivery_audit_path"])))
    ready = all([
        manual_smoke_enabled,
        sender_enabled,
        execution_enabled,
        allow_reply_current,
        current_session_enabled,
    ])

    print("[CURRENT_SESSION_SMOKE_READY_CHECK]")
    print(f"config_path={config_path if config_path is not None else 'defaults'}")
    print(f"manual_smoke_enabled={str(manual_smoke_enabled).lower()}")
    print(f"manual_smoke_owner_only={str(owner_only).lower()}")
    print(f"nonebot_sender_enabled={str(sender_enabled).lower()}")
    print(f"execution_enabled={str(execution_enabled).lower()}")
    print(f"allow_reply_current={str(allow_reply_current).lower()}")
    print(f"current_session_delivery_enabled={str(current_session_enabled).lower()}")
    print("explicit_enable_required=true")
    print("bot_event_injection_required=true")
    print(f"audit_path={audit_path}")
    print(f"dedup_ttl_seconds={dedup_ttl}")
    print("cross_session_locked=true")
    print(f"ready={str(ready).lower()}")
    if not ready:
        missing = []
        if not manual_smoke_enabled:
            missing.append("owner_action_manual_smoke_enabled")
        if not sender_enabled:
            missing.append("owner_action_nonebot_sender_enabled")
        if not execution_enabled:
            missing.append("owner_action_execution_enabled")
        if not allow_reply_current:
            missing.append("owner_action_allow_reply_current")
        if not current_session_enabled:
            missing.append("owner_action_current_session_delivery_enabled")
        print("missing=" + ",".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
