from __future__ import annotations

import argparse
import ast
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
ROOT = SCRIPT_PATH.parents[1]
DEFAULT_RUNTIME_CONFIG = ROOT / "src/plugins/yangyang/data/runtime_config.json"
SENSITIVE_ENV_KEYWORDS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "WS_URL",
    "API_ROOT",
    "BASE_URL",
)


@dataclass
class CheckResult:
    level: str
    message: str


class Reporter:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def pass_(self, message: str) -> None:
        self.results.append(CheckResult("PASS", message))

    def warn(self, message: str) -> None:
        self.results.append(CheckResult("WARN", message))

    def fail(self, message: str) -> None:
        self.results.append(CheckResult("FAIL", message))

    def print_text(self) -> None:
        print("[NONEBOT_RUNTIME_READY_CHECK]")
        for item in self.results:
            print(f"[{item.level}] {item.message}")
        summary = self.summary()
        print(
            f"[SUMMARY] pass={summary['pass']} warn={summary['warn']} fail={summary['fail']}"
        )

    def summary(self) -> dict[str, int]:
        return {
            "pass": sum(1 for item in self.results if item.level == "PASS"),
            "warn": sum(1 for item in self.results if item.level == "WARN"),
            "fail": sum(1 for item in self.results if item.level == "FAIL"),
        }

    def exit_code(self) -> int:
        return 1 if any(item.level == "FAIL" for item in self.results) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only NoneBot runtime wiring readiness check.",
    )
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    parser.add_argument("--strict", action="store_true", help="Treat WARN as FAIL in exit code")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(args.root).resolve()
    reporter = Reporter()
    run_checks(project_root, reporter)

    if args.json:
        payload = {
            "header": "NONEBOT_RUNTIME_READY_CHECK",
            "root": str(project_root),
            "results": [item.__dict__ for item in reporter.results],
            "summary": reporter.summary(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        reporter.print_text()

    if args.strict and any(item.level == "WARN" for item in reporter.results):
        return 1
    return reporter.exit_code()


def run_checks(project_root: Path, reporter: Reporter) -> None:
    files = collect_target_files(project_root)
    existing_sender = select_sender_file(files)

    for label, path in files.items():
        if path.exists():
            reporter.pass_(f"file {path.relative_to(project_root)} exists")
        else:
            if label == "env":
                reporter.warn(".env missing; create from .env.example before real OneBot run")
            elif label == "sender_primary" and existing_sender is not None:
                reporter.warn(
                    "file src/plugins/yangyang/output/nonebot_current_session_sender.py missing; "
                    f"using {existing_sender.relative_to(project_root)} as actual sender adapter"
                )
            else:
                reporter.fail(f"file {path.relative_to(project_root)} missing")

    compile_python_file(project_root, files["bot"], reporter, "bot.py")
    compile_python_file(project_root, files["plugin_init"], reporter, "src/plugins/yangyang/__init__.py")
    compile_python_file(
        project_root,
        files["smoke_trigger"],
        reporter,
        "src/plugins/yangyang/output/current_session_smoke_trigger.py",
    )
    if existing_sender is not None:
        compile_python_file(project_root, existing_sender, reporter, str(existing_sender.relative_to(project_root)))

    pyproject_text = safe_read_text(files["pyproject"])
    check_dependencies(pyproject_text, reporter)
    check_import("nonebot", "nonebot2", reporter, hard_fail=True)
    check_import(
        "nonebot.adapters.onebot.v11",
        "OneBot v11 adapter",
        reporter,
        hard_fail=True,
    )

    env_example_text = safe_read_text(files["env_example"])
    check_env_example(env_example_text, reporter)
    check_env_file(files["env"], reporter)
    check_runtime_config(project_root, reporter)
    check_plugin_loading_and_hooking(project_root, pyproject_text, files, existing_sender, reporter)
    check_safety_guards(project_root, reporter)


def collect_target_files(project_root: Path) -> dict[str, Path]:
    return {
        "bot": project_root / "bot.py",
        "pyproject": project_root / "pyproject.toml",
        "env_example": project_root / ".env.example",
        "env": project_root / ".env",
        "plugin_init": project_root / "src/plugins/yangyang/__init__.py",
        "smoke_trigger": project_root / "src/plugins/yangyang/output/current_session_smoke_trigger.py",
        "sender_primary": project_root / "src/plugins/yangyang/output/nonebot_current_session_sender.py",
        "sender_adapter_factory": project_root / "src/plugins/yangyang/output/sender_adapter_factory.py",
        "sender_adapter": project_root / "src/plugins/yangyang/output/sender_adapter.py",
        "runtime_config": project_root / "src/plugins/yangyang/data/runtime_config.json",
    }


def select_sender_file(files: dict[str, Path]) -> Path | None:
    if files["sender_primary"].exists():
        return files["sender_primary"]
    if files["sender_adapter"].exists():
        return files["sender_adapter"]
    if files["sender_adapter_factory"].exists():
        return files["sender_adapter_factory"]
    return None


def compile_python_file(project_root: Path, path: Path, reporter: Reporter, label: str) -> None:
    if not path.exists():
        reporter.fail(f"compile skipped; file missing: {label}")
        return
    try:
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
        compile(source, str(path), "exec")
        reporter.pass_(f"compile {label} ok")
    except Exception as exc:
        reporter.fail(f"compile {label} failed: {exc.__class__.__name__}: {exc}")


def check_dependencies(pyproject_text: str, reporter: Reporter) -> None:
    if not pyproject_text.strip():
        reporter.fail("pyproject.toml unreadable or empty")
        return
    lowered = pyproject_text.lower()
    if "nonebot2" in lowered:
        reporter.pass_("pyproject.toml declares nonebot2 dependency hint")
    else:
        reporter.fail("pyproject.toml missing nonebot2 dependency hint")
    if "nonebot-adapter-onebot" in lowered or "onebot" in lowered:
        reporter.pass_("pyproject.toml declares onebot adapter dependency hint")
    else:
        reporter.fail("pyproject.toml missing onebot adapter dependency hint")


def check_import(module_name: str, display_name: str, reporter: Reporter, hard_fail: bool) -> None:
    try:
        importlib.import_module(module_name)
        reporter.pass_(f"import {display_name} ok")
    except Exception as exc:
        message = (
            f"import {display_name} failed: {exc.__class__.__name__}: {exc}; "
            f"suggestion: pip install -e .[nonebot]"
        )
        if hard_fail:
            reporter.fail(message)
        else:
            reporter.warn(message)


def check_env_example(env_example_text: str, reporter: Reporter) -> None:
    if not env_example_text.strip():
        reporter.fail(".env.example unreadable or empty")
        return
    required_keys = [
        "DRIVER",
        "HOST",
        "PORT",
        "ONEBOT_WS_URL",
    ]
    optional_hints = ["ONEBOT_ACCESS_TOKEN", "ONEBOT_SECRET", "ONEBOT_API_ROOT", "ONEBOT_WS_REVERSE_URL"]
    missing_required = [key for key in required_keys if key not in env_example_text]
    missing_optional = [key for key in optional_hints if key not in env_example_text]
    if missing_required:
        reporter.fail(
            ".env.example missing key hints: " + ", ".join(missing_required)
        )
    else:
        reporter.pass_(".env.example includes driver/host/port/websocket key hints")
    if missing_optional:
        reporter.warn(
            ".env.example missing optional onebot hints: " + ", ".join(missing_optional)
        )
    else:
        reporter.pass_(".env.example includes token/secret/api/websocket reverse hints")


def parse_env_keys(path: Path) -> list[str]:
    keys: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.append(key)
    return keys


def check_env_file(env_path: Path, reporter: Reporter) -> None:
    if not env_path.exists():
        reporter.warn(".env missing; create from .env.example before real OneBot run")
        return
    try:
        keys = parse_env_keys(env_path)
    except Exception as exc:
        reporter.fail(f".env unreadable: {exc.__class__.__name__}: {exc}")
        return
    if not keys:
        reporter.warn(".env exists but no parseable keys found")
        return
    key_text = ", ".join(sorted(keys))
    reporter.pass_(f".env exists; parsed keys only: {key_text}")
    sensitive_present = [key for key in keys if any(word in key.upper() for word in SENSITIVE_ENV_KEYWORDS)]
    if sensitive_present:
        reporter.pass_(
            ".env sensitive values redacted; observed sensitive key names only: "
            + ", ".join(sorted(sensitive_present))
        )


def check_runtime_config(project_root: Path, reporter: Reporter) -> None:
    config_path = project_root / "src/plugins/yangyang/data/runtime_config.json"
    if not config_path.exists():
        reporter.fail("runtime_config.json missing")
        return
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        reporter.fail(f"runtime_config.json unreadable: {exc.__class__.__name__}: {exc}")
        return
    if not isinstance(data, dict):
        reporter.fail("runtime_config.json root is not a JSON object")
        return

    smoke_enabled = to_bool(data.get("owner_action_manual_smoke_enabled", False))
    sender_enabled = to_bool(data.get("owner_action_nonebot_sender_enabled", False))
    allow_reply_current = to_bool(data.get("owner_action_allow_reply_current", False))
    current_session_enabled = to_bool(data.get("owner_action_current_session_delivery_enabled", False))
    cross_group_enabled = to_bool(data.get("owner_action_allow_send_group_message", False))
    audit_enabled = to_bool(data.get("owner_action_delivery_audit_enabled", True))
    audit_path_raw = str(data.get("owner_action_delivery_audit_path", "logs/owner_action_delivery_audit.jsonl") or "").strip()

    if not smoke_enabled:
        reporter.pass_("runtime_config.json smoke safe state ok: owner_action_manual_smoke_enabled=false")
    else:
        reporter.warn("runtime_config.json smoke currently enabled; disable before idle state and only toggle before real smoke")

    if not sender_enabled and not allow_reply_current and not current_session_enabled:
        reporter.pass_("runtime_config.json sender/delivery gates are closed by default")
    else:
        reporter.warn("runtime_config.json current-session sender gates are open; verify this is intentional before real smoke")

    if not cross_group_enabled:
        reporter.pass_("runtime_config.json cross-group send gate remains locked")
    else:
        reporter.fail("runtime_config.json owner_action_allow_send_group_message=true; cross-group send must stay locked")

    audit_path = Path(audit_path_raw) if audit_path_raw else Path("logs/owner_action_delivery_audit.jsonl")
    resolved_audit_path = audit_path if audit_path.is_absolute() else project_root / audit_path
    if audit_enabled:
        if resolved_audit_path.exists():
            reporter.pass_(f"audit path exists: {resolved_audit_path}")
        elif resolved_audit_path.parent.exists() or resolved_audit_path.parent.parent.exists() or resolved_audit_path.parent == project_root:
            reporter.pass_(f"audit parent directory available for creation: {resolved_audit_path.parent}")
        else:
            reporter.warn(f"audit path parent missing; ensure creatable before real smoke: {resolved_audit_path.parent}")
    else:
        reporter.warn("owner_action_delivery_audit_enabled=false; audit trail disabled")


def check_plugin_loading_and_hooking(
    project_root: Path,
    pyproject_text: str,
    files: dict[str, Path],
    existing_sender: Path | None,
    reporter: Reporter,
) -> None:
    bot_text = safe_read_text(files["bot"])
    init_text = safe_read_text(files["plugin_init"])
    trigger_text = safe_read_text(files["smoke_trigger"])

    if "nonebot.load_plugins" in bot_text and "src/plugins" in bot_text:
        reporter.pass_("bot.py loads plugins from src/plugins")
    elif "load_plugin" in bot_text or "load_plugins" in bot_text:
        reporter.warn("bot.py appears to load plugins, but plugin path wiring is not statically obvious")
    else:
        reporter.fail("bot.py missing obvious plugin loading call")

    if "register_adapter" in bot_text and "OneBotV11Adapter" in bot_text:
        reporter.pass_("bot.py registers OneBot v11 adapter")
    else:
        reporter.fail("bot.py missing obvious OneBot v11 adapter registration")

    if "load_dotenv" in bot_text and ".env" in bot_text:
        reporter.pass_("bot.py reads .env before init")
    else:
        reporter.warn("bot.py .env loading is not statically obvious")

    if "handle_current_session_smoke_trigger_if_matched" in init_text:
        reporter.pass_("plugin __init__.py references current-session smoke trigger hook")
    else:
        reporter.fail("plugin __init__.py missing smoke trigger hook reference")

    if "parse_current_session_smoke_trigger_command" in init_text:
        reporter.pass_("plugin __init__.py pre-checks smoke trigger command before hook")
    else:
        reporter.warn("plugin __init__.py smoke pre-check is not statically obvious")

    if "handle_message(bot: Bot, event)" in init_text or "handle_message(bot: Bot, event):" in init_text:
        reporter.pass_("plugin hook can receive bot/event objects")
    elif "handle_message" in init_text and "bot" in init_text and "event" in init_text:
        reporter.warn("plugin entry likely receives bot/event, but signature check is heuristic")
    else:
        reporter.warn("plugin entry bot/event wiring is not statically obvious")

    if "run_current_session_manual_smoke_if_enabled" in trigger_text and "explicit_enable=True" in trigger_text:
        reporter.pass_("smoke trigger delegates to manual smoke with explicit_enable gate")
    else:
        reporter.warn("smoke trigger manual-smoke delegation not fully obvious from static text")

    if existing_sender is not None and "NoneBotCurrentSessionSenderAdapter" in safe_read_text(existing_sender):
        reporter.pass_(f"sender adapter implementation present in {existing_sender.relative_to(project_root)}")
    elif existing_sender is not None:
        reporter.warn(f"sender-related file present but NoneBot sender class not obvious: {existing_sender.relative_to(project_root)}")
    else:
        reporter.fail("no sender adapter file found for current-session wiring")

    if "pythonpath = [\"src\"]" in pyproject_text or "package-dir = {\"\" = \"src\"}" in pyproject_text:
        reporter.pass_("pyproject.toml exposes src-based package layout")
    else:
        reporter.warn("pyproject.toml src package wiring is not statically obvious")


def check_safety_guards(project_root: Path, reporter: Reporter) -> None:
    init_text = safe_read_text(project_root / "src/plugins/yangyang/__init__.py")
    trigger_text = safe_read_text(project_root / "src/plugins/yangyang/output/current_session_smoke_trigger.py")
    manual_smoke_text = safe_read_text(project_root / "src/plugins/yangyang/output/current_session_manual_smoke.py")
    sender_factory_text = safe_read_text(project_root / "src/plugins/yangyang/output/sender_adapter_factory.py")

    if "smoke_command.matched" in init_text:
        reporter.pass_("ordinary owner action does not auto-send; smoke branch is prefix-gated")
    else:
        reporter.warn("ordinary owner action anti-auto-send gate not statically obvious")

    if "cross_session_blocked" in trigger_text and "send_group_message" in trigger_text:
        reporter.pass_("trigger layer blocks cross-session/group smoke paths")
    else:
        reporter.fail("trigger layer cross-session block not obvious")

    if "action_type != \"reply_current\"" in manual_smoke_text and "destination_type != \"current_session\"" in manual_smoke_text:
        reporter.pass_("manual smoke restricts action to reply_current/current_session")
    else:
        reporter.warn("manual smoke current-session restriction not fully obvious")

    if "owner_action_allow_reply_current" in sender_factory_text and "owner_action_current_session_delivery_enabled" in sender_factory_text:
        reporter.pass_("sender factory requires explicit current-session delivery gates")
    else:
        reporter.warn("sender factory delivery gating not statically obvious")

    if "owner_action_allow_send_group_message" in safe_read_text(project_root / "src/plugins/yangyang/data/runtime_config.json"):
        reporter.pass_("runtime config contains explicit cross-group allow flag for lock-state inspection")
    else:
        reporter.warn("runtime config missing explicit cross-group allow flag")


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
