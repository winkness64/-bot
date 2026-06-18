from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = "src/plugins/yangyang/data/runtime_config.json"
DEFAULT_BACKUP_DIR = "backups/runtime_config"

ENABLE_TARGETS: dict[str, Any] = {
    "owner_action_manual_smoke_enabled": True,
    "owner_action_nonebot_sender_enabled": True,
    "owner_action_execution_enabled": True,
    "owner_action_allow_reply_current": True,
    "owner_action_current_session_delivery_enabled": True,
    "owner_action_manual_smoke_owner_only": True,
    "owner_action_delivery_safety_enabled": True,
    "owner_action_delivery_audit_enabled": True,
}

DISABLE_TARGETS: dict[str, Any] = {
    "owner_action_manual_smoke_enabled": False,
    "owner_action_nonebot_sender_enabled": False,
    "owner_action_execution_enabled": False,
    "owner_action_allow_reply_current": False,
    "owner_action_current_session_delivery_enabled": False,
    "owner_action_manual_smoke_owner_only": True,
    "owner_action_delivery_safety_enabled": True,
    "owner_action_delivery_audit_enabled": True,
}

READY_KEYS = [
    "owner_action_manual_smoke_enabled",
    "owner_action_manual_smoke_owner_only",
    "owner_action_nonebot_sender_enabled",
    "owner_action_execution_enabled",
    "owner_action_allow_reply_current",
    "owner_action_current_session_delivery_enabled",
    "owner_action_delivery_safety_enabled",
    "owner_action_delivery_audit_enabled",
]

FORBIDDEN_CROSS_SESSION_KEYS = [
    "owner_action_allow_send_group_message",
    "send_group_message",
    "cross_session",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Toggle current-session smoke config safely without connecting QQ/OneBot.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--show", action="store_true", help="Show current smoke-related config status")
    mode.add_argument("--enable", action="store_true", help="Enable current-session manual smoke required toggles")
    mode.add_argument("--disable", action="store_true", help="Disable dangerous smoke toggles and return to safe state")
    mode.add_argument("--restore", help="Restore runtime config from a backup JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Print intended changes without writing file")
    parser.add_argument("--yes", action="store_true", help="Non-interactive confirmation")
    parser.add_argument("--backup", action="store_true", help="Compatibility flag; write operations already auto-backup by default")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Path to runtime_config.json")
    return parser


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config root must be a JSON object")
    return raw


def dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def backup_dir_for_config(config_path: Path) -> Path:
    return config_path.parent.parent.parent.parent / DEFAULT_BACKUP_DIR if "src/plugins/yangyang/data" in str(config_path).replace('\\', '/') else Path.cwd() / DEFAULT_BACKUP_DIR


def create_backup(config_path: Path) -> Path:
    backup_dir = backup_dir_for_config(config_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"runtime_config.{timestamp}.json"
    suffix = 1
    while target.exists():
        target = backup_dir / f"runtime_config.{timestamp}.{suffix}.json"
        suffix += 1
    shutil.copy2(config_path, target)
    return target


def changed_keys(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [key for key in keys if before.get(key) != after.get(key)]


def apply_targets(base: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    updated = dict(base)
    for key, value in targets.items():
        updated[key] = value
    return updated


def print_status(config_path: Path, data: dict[str, Any], *, heading: str = "CURRENT_SESSION_SMOKE_STATUS") -> None:
    print(f"[{heading}]")
    print(f"config_path={config_path}")
    for key in READY_KEYS:
        print(f"{key}={str(to_bool(data.get(key))).lower()}")
    ready = all(to_bool(data.get(key)) for key in [
        "owner_action_manual_smoke_enabled",
        "owner_action_nonebot_sender_enabled",
        "owner_action_execution_enabled",
        "owner_action_allow_reply_current",
        "owner_action_current_session_delivery_enabled",
    ])
    print(f"ready={str(ready).lower()}")
    print("explicit_enable_required=true")
    print("bot_event_injection_required=true")
    print("cross_session_send_group_message_locked=true")
    for key in FORBIDDEN_CROSS_SESSION_KEYS:
        if key in data:
            value = data.get(key)
            if isinstance(value, bool):
                value = str(value).lower()
            print(f"observe_{key}={value}")
    print("reminder=enable_does_not_auto_send; still_need_explicit_enable_true_and_bot_event_injection; cross_group_send_group_message_stays_locked")


def print_change_summary(before: dict[str, Any], after: dict[str, Any]) -> None:
    keys = changed_keys(before, after)
    if keys:
        print("changed_keys=" + ",".join(keys))
        for key in keys:
            print(f"  {key}: {before.get(key)!r} -> {after.get(key)!r}")
    else:
        print("changed_keys=(none)")


def confirm_or_cancel(message: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin or not sys.stdin.isatty():
        print("cancelled=non_interactive_confirmation_required")
        return False
    try:
        answer = input(f"{message} [y/N]: ").strip().lower()
    except EOFError:
        print("cancelled=confirmation_input_unavailable")
        return False
    if answer not in {"y", "yes"}:
        print("cancelled=user_declined")
        return False
    return True


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_config(path: Path, data: dict[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(dump_json(data), encoding="utf-8")


def restore_from_backup(config_path: Path, restore_path: Path, *, dry_run: bool, yes: bool) -> int:
    if not restore_path.exists():
        print(f"error=restore_backup_not_found path={restore_path}")
        return 1
    try:
        restored = load_json(restore_path)
    except Exception as exc:
        print(f"error=restore_backup_invalid_json detail={exc}")
        return 1

    current = load_json(config_path) if config_path.exists() else {}
    print(f"restore_from={restore_path}")
    print_change_summary(current, restored)
    print_status(config_path, restored, heading="CURRENT_SESSION_SMOKE_RESTORE_PREVIEW")

    if dry_run:
        print("dry_run=true")
        return 0

    if not confirm_or_cancel("Restore runtime config from backup?", assume_yes=yes):
        return 0

    backup_path = None
    if config_path.exists():
        backup_path = create_backup(config_path)
        print(f"backup_path={backup_path}")
    write_config(config_path, restored)
    print("restored=true")
    print_status(config_path, load_json(config_path), heading="CURRENT_SESSION_SMOKE_STATUS")
    return 0


def mutate_config(config_path: Path, *, targets: dict[str, Any], action_name: str, dry_run: bool, yes: bool) -> int:
    current = load_json(config_path)
    updated = apply_targets(current, targets)

    print(f"action={action_name}")
    print_change_summary(current, updated)
    print_status(config_path, updated, heading="CURRENT_SESSION_SMOKE_PREVIEW")

    if dry_run:
        print("dry_run=true")
        return 0

    if action_name == "enable":
        if not confirm_or_cancel("Enable current-session smoke toggles for this config?", assume_yes=yes):
            return 0
    else:
        if not confirm_or_cancel("Disable current-session smoke toggles and return to safe state?", assume_yes=yes):
            return 0

    backup_path = create_backup(config_path)
    print(f"backup_path={backup_path}")
    write_config(config_path, updated)
    print("written=true")
    print_status(config_path, load_json(config_path), heading="CURRENT_SESSION_SMOKE_STATUS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = Path(args.config)

    if args.show:
        data = load_json(config_path) if config_path.exists() else {}
        print_status(config_path, data)
        return 0

    if args.restore:
        return restore_from_backup(
            config_path,
            Path(args.restore),
            dry_run=bool(args.dry_run),
            yes=bool(args.yes),
        )

    if not config_path.exists():
        print(f"error=config_not_found path={config_path}")
        return 1

    if args.enable:
        return mutate_config(
            config_path,
            targets=ENABLE_TARGETS,
            action_name="enable",
            dry_run=bool(args.dry_run),
            yes=bool(args.yes),
        )

    if args.disable:
        return mutate_config(
            config_path,
            targets=DISABLE_TARGETS,
            action_name="disable",
            dry_run=bool(args.dry_run),
            yes=bool(args.yes),
        )

    parser.error("one action is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
