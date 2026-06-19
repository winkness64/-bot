from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CST = timezone(timedelta(hours=8))
# core/token_usage.py -> core -> yangyang -> plugins -> src -> <project_root>
PROJECT_ROOT = Path(__file__).resolve().parents[4]


@dataclass(slots=True)
class TokenUsageSummary:
    available: bool
    total_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    since_ts: str = ""
    last_ts: str = ""
    last_model: str = ""
    last_tier: str = ""
    reason: str = ""
    period: str = "all"
    group_by: str = "none"
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_hour: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_day: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_month: dict[str, dict[str, Any]] = field(default_factory=dict)


def _cfg_get(config: Any, path: str, default: Any = None) -> Any:
    try:
        if config is not None and hasattr(config, "get"):
            value = config.get(path, default)
            return default if value is None else value
    except Exception:
        return default
    if isinstance(config, dict):
        cur: Any = config
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur
    return default


def resolve_token_usage_log_path(config: Any = None, *, project_root: str | Path | None = None) -> Path:
    raw = str(_cfg_get(config, "token_usage_log_path", "logs/token_usage.jsonl") or "logs/token_usage.jsonl")
    path = Path(raw)
    if not path.is_absolute():
        root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
        path = root / path
    return path


def append_token_usage_event(
    config: Any,
    *,
    project_root: str | Path | None = None,
    request_id: str = "",
    session_id: str = "",
    channel: str = "",
    tier: str = "",
    model: str = "",
    provider: str = "",
    token_usage: dict[str, Any] | None = None,
    tool_call_count: int = 0,
) -> bool:
    usage = token_usage or {}
    if not isinstance(usage, dict) or not usage:
        return False

    def _int(name: str) -> int:
        try:
            return max(0, int(usage.get(name) or 0))
        except Exception:
            return 0

    prompt_tokens = _int("prompt_tokens")
    completion_tokens = _int("completion_tokens")
    total_tokens = _int("total_tokens") or (prompt_tokens + completion_tokens)
    if prompt_tokens <= 0 and completion_tokens <= 0 and total_tokens <= 0:
        return False
    path = resolve_token_usage_log_path(config, project_root=project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "request_id": str(request_id or ""),
        "session_id": str(session_id or ""),
        "channel": str(channel or ""),
        "tier": str(tier or ""),
        "model": str(model or ""),
        "provider": str(provider or ""),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "tool_call_count": max(0, int(tool_call_count or 0)),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return True


def _parse_dt(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _period_cutoff(period: str | None, *, hours: int | None = None) -> tuple[datetime | None, str]:
    if hours is not None:
        try:
            h = max(1, int(hours))
            return datetime.now(timezone.utc) - timedelta(hours=h), f"last_{h}h"
        except Exception:
            pass
    key = str(period or "all").strip().lower()
    now = datetime.now(CST)
    if key in {"hour", "current_hour", "this_hour", "小时", "本小时"}:
        return now.replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc), "hour"
    if key in {"today", "day", "current_day", "this_day", "今天", "今日", "本日"}:
        return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc), "today"
    if key in {"month", "current_month", "this_month", "本月", "这个月", "月"}:
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc), "month"
    return None, "all"


def _bucket_inc(bucket: dict[str, dict[str, Any]], key: str, *, prompt: int, completion: int, total: int, calls: int = 1) -> None:
    item = bucket.setdefault(key, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    item["calls"] += calls
    item["prompt_tokens"] += prompt
    item["completion_tokens"] += completion
    item["total_tokens"] += total


def _event_model_key(item: dict[str, Any]) -> str:
    model = str(item.get("model") or "unknown").strip() or "unknown"
    tier = str(item.get("tier") or "").strip()
    return f"{model}（{tier}）" if tier else model


def summarize_token_usage(
    config: Any = None,
    *,
    project_root: str | Path | None = None,
    session_id: str | None = None,
    hours: int | None = None,
    period: str | None = None,
    group_by: str | None = None,
) -> TokenUsageSummary:
    path = resolve_token_usage_log_path(config, project_root=project_root)
    normalized_group = str(group_by or "none").strip().lower() or "none"
    cutoff, normalized_period = _period_cutoff(period, hours=hours)
    if not path.exists():
        return TokenUsageSummary(available=False, reason="no_usage_log", period=normalized_period, group_by=normalized_group)

    summary = TokenUsageSummary(available=True, period=normalized_period, group_by=normalized_group)
    wanted_session = str(session_id or "").strip()
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(item, dict):
                    continue
                if wanted_session and str(item.get("session_id") or "") != wanted_session:
                    continue
                ts = str(item.get("ts") or "")
                dt = _parse_dt(ts)
                if cutoff is not None and dt is not None and dt < cutoff:
                    continue
                prompt = int(item.get("prompt_tokens") or 0)
                completion = int(item.get("completion_tokens") or 0)
                total = int(item.get("total_tokens") or 0) or (prompt + completion)
                tools = int(item.get("tool_call_count") or 0)
                summary.total_calls += 1
                summary.prompt_tokens += prompt
                summary.completion_tokens += completion
                summary.total_tokens += total
                summary.tool_calls += tools
                if not summary.since_ts:
                    summary.since_ts = ts
                summary.last_ts = ts
                summary.last_model = str(item.get("model") or "")
                summary.last_tier = str(item.get("tier") or "")
                _bucket_inc(summary.by_model, _event_model_key(item), prompt=prompt, completion=completion, total=total)
                if dt is not None:
                    cst = dt.astimezone(CST)
                    _bucket_inc(summary.by_hour, cst.strftime("%Y-%m-%d %H:00"), prompt=prompt, completion=completion, total=total)
                    _bucket_inc(summary.by_day, cst.strftime("%Y-%m-%d"), prompt=prompt, completion=completion, total=total)
                    _bucket_inc(summary.by_month, cst.strftime("%Y-%m"), prompt=prompt, completion=completion, total=total)
    except Exception:
        return TokenUsageSummary(available=False, reason="read_failed", period=normalized_period, group_by=normalized_group)
    if summary.total_calls <= 0:
        return TokenUsageSummary(available=False, reason="no_matching_usage", period=normalized_period, group_by=normalized_group)
    return summary


def _top_bucket_lines(title: str, bucket: dict[str, dict[str, Any]], *, limit: int = 8) -> list[str]:
    if not bucket:
        return []
    rows = sorted(bucket.items(), key=lambda kv: int(kv[1].get("total_tokens") or 0), reverse=True)[: max(1, limit)]
    lines = [title]
    for key, item in rows:
        lines.append(
            f"- {key}: {int(item.get('total_tokens') or 0)} tokens "
            f"（输入 {int(item.get('prompt_tokens') or 0)} / 输出 {int(item.get('completion_tokens') or 0)} / {int(item.get('calls') or 0)} 次）"
        )
    return lines


def format_token_usage_summary(summary: TokenUsageSummary, *, title: str = "Token 用量", group_by: str | None = None) -> str:
    if not summary.available:
        return "漂♂总，我这边还没有可用的 token 统计记录。等后续模型调用写入 usage 后就能查。"
    group = str(group_by or summary.group_by or "none").strip().lower()
    parts = [
        f"{title}：共 {summary.total_tokens} tokens。",
        f"输入 {summary.prompt_tokens}，输出 {summary.completion_tokens}，调用 {summary.total_calls} 次。",
    ]
    if summary.tool_calls:
        parts.append(f"其中工具链调用 {summary.tool_calls} 次。")
    if summary.last_model:
        parts.append(f"最近一次模型：{summary.last_model}（{summary.last_tier or '-'}）。")
    if group in {"model", "models", "by_model", "all", "模型", "按模型"}:
        parts.extend(_top_bucket_lines("按模型：", summary.by_model))
    if group in {"hour", "hours", "by_hour", "all", "小时", "按小时"}:
        parts.extend(_top_bucket_lines("按小时：", summary.by_hour))
    if group in {"day", "daily", "by_day", "all", "天", "按天", "日"}:
        parts.extend(_top_bucket_lines("按天：", summary.by_day))
    if group in {"month", "monthly", "by_month", "all", "月", "按月"}:
        parts.extend(_top_bucket_lines("按月：", summary.by_month))
    return "\n".join(parts)


def format_token_usage_push_summary(
    recent: TokenUsageSummary,
    *,
    hours: int = 1,
    today: TokenUsageSummary | None = None,
    group_by: str | None = "model",
) -> str:
    """Format scheduled token push without pretending an empty recent window means no ledger.

    The hourly scheduler asks for a small recent window.  When that window has no
    model calls but the ledger has today's accumulated records, report "no new
    calls" plus the daily total instead of the generic "no usage log" text.
    """
    safe_hours = max(1, int(hours or 1))
    if recent.available:
        return format_token_usage_summary(recent, title=f"最近 {safe_hours} 小时 Token 用量", group_by=group_by)

    if today is not None and today.available:
        daily = format_token_usage_summary(today, title="今日累计 Token 用量", group_by=group_by)
        return f"最近 {safe_hours} 小时没有新增模型调用。\n\n{daily}"

    return format_token_usage_summary(recent, title=f"最近 {safe_hours} 小时 Token 用量", group_by=group_by)
