from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nonebot.log import logger

try:
    from nonebot import get_bot
except ImportError:
    get_bot = None

from ..core.isaac_agentbus_factory_report import build_agentbus_factory_report, format_agentbus_factory_report
from ..output.factory_completion_current_session_bridge import notify_owner_current_session_on_factory_completion

DEFAULT_STATE_PATH = Path("data/factory_notifier_state.json")
COMPLETION_STATES = {"COLLECTED", "STOPPED", "MANUAL_CLOSED", "ABORTED"}


def _get_runtime_config():
    import sys
    import importlib
    package_name = str(__package__ or "")
    parent_name = package_name.rsplit(".", 1)[0] if "." in package_name else "plugins.yangyang"
    module = sys.modules.get(parent_name)
    if module is not None:
        return getattr(module, "cfg", None)
    try:
        module = importlib.import_module(parent_name)
        return getattr(module, "cfg", None)
    except ImportError:
        return None


def _load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state_path: Path, state: dict[str, Any]) -> None:
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"FactoryNotifier: failed to save state: {exc}")


def _extract_completion_state(report: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    latest = report.get("latest") if isinstance(report.get("latest"), dict) else None
    if latest:
        state = str(latest.get("activity_state") or "").upper()
        if state:
            return state, dict(latest)
    recent_runs = report.get("recent_runs") if isinstance(report.get("recent_runs"), list) else []
    if recent_runs:
        first = recent_runs[0] if isinstance(recent_runs[0], dict) else None
        if first:
            state = str(first.get("activity_state") or "").upper()
            if state:
                return state, dict(first)
    latest_run = report.get("latest_run") if isinstance(report.get("latest_run"), dict) else None
    if latest_run:
        state = str(latest_run.get("activity_state") or "").upper()
        return state, dict(latest_run)
    return "", {}


async def run_factory_completion_notifier() -> None:
    """定时任务：检查工厂是否新收工，并向 owner 投递摘要。"""
    config = _get_runtime_config()
    if config is None:
        logger.warning("FactoryNotifier: skip — runtime config unavailable")
        return
        
    try:
        enabled = bool(config.get_bool("owner_action_auto_reply_current_production_enabled", True)) if hasattr(config, "get_bool") else bool(config.get("owner_action_auto_reply_current_production_enabled", True))
    except Exception:
        enabled = True
        
    if not enabled:
        logger.info("FactoryNotifier: skip — production auto reply disabled")
        return

    owner_uid = ""
    try:
        owner_uid = str(config.get("owner_uid", "") or "")
    except Exception:
        pass
        
    if not owner_uid:
        logger.warning("FactoryNotifier: skip — owner_uid missing")
        return

    if get_bot is None:
        logger.warning("FactoryNotifier: skip — nonebot get_bot unavailable")
        return
        
    try:
        bot = get_bot()
    except Exception as exc:
        logger.warning(f"FactoryNotifier: skip — get_bot failed: {exc}")
        return

    try:
        report = build_agentbus_factory_report()
    except Exception as exc:
        logger.warning(f"FactoryNotifier: failed to build report: {exc}")
        return

    completion_state, latest_activity = _extract_completion_state(report)
    latest_run = dict(report.get("latest_run") or {})
    run_name = str(latest_run.get("name") or latest_activity.get("name") or "")

    if not run_name or completion_state not in COMPLETION_STATES:
        logger.info(
            f"FactoryNotifier: skip — run not eligible run_name={run_name or '<empty>'} completion_state={completion_state or '<empty>'}"
        )
        return

    state = _load_state(DEFAULT_STATE_PATH)
    last_notified = str(state.get("last_notified_run_id") or "")
    
    if run_name == last_notified:
        logger.info(f"FactoryNotifier: skip — already notified run {run_name}")
        return

    summary_text = format_agentbus_factory_report(report)
    if not summary_text:
        logger.warning(f"FactoryNotifier: skip — empty summary for run {run_name}")
        return

    try:
        result = await notify_owner_current_session_on_factory_completion(
            summary_text=summary_text,
            config=config,
            bot=bot,
            owner_uid=owner_uid,
            explicit_enable=True,
            dry_run=False,
        )
        
        if result.attempted:
            logger.info(f"FactoryNotifier: notified owner for run {run_name}, delivered={result.delivered}")
            state["last_notified_run_id"] = run_name
            _save_state(DEFAULT_STATE_PATH, state)
        else:
            logger.warning(f"FactoryNotifier: notification blocked for run {run_name}, reason={result.reason}")
            
    except Exception as exc:
        logger.exception(f"FactoryNotifier: failed to notify owner: {exc}")
