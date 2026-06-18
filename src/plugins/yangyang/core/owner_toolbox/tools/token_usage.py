from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

try:
    from ...token_usage import format_token_usage_summary, summarize_token_usage
except ImportError:  # owner_toolbox_light.py can load this module as a standalone fallback in tests.
    import importlib.util
    import sys

    _token_usage_path = Path(__file__).resolve().parents[2] / "token_usage.py"
    _token_usage_spec = importlib.util.spec_from_file_location("owner_toolbox_token_usage_core", _token_usage_path)
    if _token_usage_spec is None or _token_usage_spec.loader is None:
        raise
    _token_usage_mod = importlib.util.module_from_spec(_token_usage_spec)
    sys.modules.setdefault(_token_usage_spec.name, _token_usage_mod)
    _token_usage_spec.loader.exec_module(_token_usage_mod)
    format_token_usage_summary = _token_usage_mod.format_token_usage_summary
    summarize_token_usage = _token_usage_mod.summarize_token_usage

from ..results import _result
from ..types import OwnerToolboxLightResult


def _session_id_from_args(argmap: Mapping[str, Any] | dict[str, Any]) -> str:
    return str((argmap or {}).get("session_id") or (argmap or {}).get("_session_id") or "").strip()


def _hours_from_args(argmap: Mapping[str, Any] | dict[str, Any]) -> int | None:
    raw = (argmap or {}).get("hours")
    if raw is None or raw == "":
        return None
    try:
        return max(1, min(24 * 30, int(raw)))
    except Exception:
        return None


def _period_from_args(argmap: Mapping[str, Any] | dict[str, Any]) -> str:
    raw = str((argmap or {}).get("period") or "").strip().lower()
    aliases = {
        "h": "hour", "hour": "hour", "hours": "hour", "小时": "hour", "本小时": "hour",
        "today": "today", "day": "today", "daily": "today", "今天": "today", "今日": "today",
        "month": "month", "monthly": "month", "本月": "month", "这个月": "month",
        "all": "all", "全部": "all", "总计": "all",
    }
    return aliases.get(raw, raw or "all")


def _group_by_from_args(argmap: Mapping[str, Any] | dict[str, Any]) -> str:
    raw = str((argmap or {}).get("group_by") or (argmap or {}).get("group") or "").strip().lower()
    aliases = {
        "model": "model", "models": "model", "模型": "model", "按模型": "model",
        "hour": "hour", "hours": "hour", "小时": "hour", "按小时": "hour",
        "day": "day", "daily": "day", "天": "day", "日": "day", "按天": "day",
        "month": "month", "monthly": "month", "月": "month", "按月": "month",
        "all": "all", "全部": "all", "全维度": "all",
    }
    return aliases.get(raw, raw or "none")


def handle_query_token_usage(
    config: Any,
    argmap: Mapping[str, Any] | dict[str, Any],
    *,
    project_root: str | Path | None = None,
    tool: str = "query_token_usage",
) -> OwnerToolboxLightResult:
    session_id = _session_id_from_args(argmap)
    hours = _hours_from_args(argmap)
    period = _period_from_args(argmap)
    group_by = _group_by_from_args(argmap)
    summary = summarize_token_usage(config, project_root=project_root, session_id=session_id or None, hours=hours, period=period, group_by=group_by)
    title = "当前会话 Token 用量" if session_id else "Token 用量"
    if hours:
        title = f"最近 {hours} 小时 " + title
    elif period == "hour":
        title = "本小时 " + title
    elif period == "today":
        title = "今日 " + title
    elif period == "month":
        title = "本月 " + title
    reply = format_token_usage_summary(summary, title=title, group_by=group_by)
    return _result(
        allowed=bool(summary.available),
        reason="ok" if summary.available else (summary.reason or "no_usage"),
        reply=reply,
        tool_name=tool,
        output=reply,
        data={
            "available": summary.available,
            "total_calls": summary.total_calls,
            "prompt_tokens": summary.prompt_tokens,
            "completion_tokens": summary.completion_tokens,
            "total_tokens": summary.total_tokens,
            "tool_calls": summary.tool_calls,
            "since_ts": summary.since_ts,
            "last_ts": summary.last_ts,
            "last_model": summary.last_model,
            "last_tier": summary.last_tier,
            "session_id_provided": bool(session_id),
            "hours": hours,
            "period": summary.period,
            "group_by": summary.group_by,
            "by_model": summary.by_model,
            "by_hour": summary.by_hour,
            "by_day": summary.by_day,
            "by_month": summary.by_month,
            "reason": summary.reason,
        },
    )
