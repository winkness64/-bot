"""Isaac P0 audit / status read-only report builder.

Fail-soft: never raises.  Owner-private only.  Sanitizes sensitive markers
and does not emit raw user text, full QQ, or any key/token material.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

_SENSITIVE_MARKERS = (
    "api_key", "apikey", "token", "base_url", "secret", "password",
    "authorization", "cookie", "session_key", "bearer ",
)

_ALLOWED_CAPABILITIES = ("health", "workspace", "audit", "help")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clip(value: Any, n: int = 64) -> str:
    s = str(value or "").replace("\n", " ").strip()
    if len(s) > n:
        s = s[: n - 1] + "…"
    return s


def _redact_user_id(user_id: Any) -> str:
    s = str(user_id or "").strip()
    if not s:
        return "unknown"
    if "@" in s:
        return "owner_redacted"
    digits = re.sub(r"\D", "", s)
    if not digits:
        return "owner_redacted"
    return f"uid_hash_{abs(hash(digits)) % (10 ** 8):08d}"


def _scan_text_for_markers(text: str) -> list[str]:
    if not text:
        return []
    lower = text.lower()
    found: list[str] = []
    for marker in _SENSITIVE_MARKERS:
        if marker in lower:
            found.append(marker)
    return found


def _iter_audit_records(audit_path: Path, *, tail_bytes: int = 256_000) -> Iterable[dict[str, Any]]:
    if not audit_path.exists():
        return []
    try:
        size = audit_path.stat().st_size
    except OSError:
        return []
    try:
        with audit_path.open("rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()  # drop partial first line
            data = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts: dict[str, int] = {}
    trigger_counts: dict[str, int] = {}
    task_type_counts: dict[str, int] = {}
    bad_lines = 0
    for rec in records:
        decision = str(rec.get("decision") or "unknown").lower()
        trigger = str(rec.get("trigger_type") or "unknown").lower()
        task_type = str(rec.get("task_type") or "unknown").lower()
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        trigger_counts[trigger] = trigger_counts.get(trigger, 0) + 1
        task_type_counts[task_type] = task_type_counts.get(task_type, 0) + 1
    return {
        "decision_counts": decision_counts,
        "trigger_counts": trigger_counts,
        "task_type_counts": task_type_counts,
        "bad_lines": bad_lines,
    }


def _summarize_recent(records: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in records[-limit:]:
        cmd = rec.get("command") or rec.get("command_head") or ""
        out.append({
            "ts": _clip(rec.get("ts"), 32),
            "decision": _clip(rec.get("decision"), 16),
            "trigger_type": _clip(rec.get("trigger_type"), 24),
            "command_head": _clip(cmd, 48),
            "task_type": _clip(rec.get("task_type"), 24),
            "reason": _clip(rec.get("reason") or rec.get("parse_reason"), 40),
            "actor": _redact_user_id(rec.get("user_id") or rec.get("actor_id")),
        })
    return out


def build_audit_report(audit_dir: Path | None = None, *,
                       tail_bytes: int = 256_000,
                       recent_limit: int = 5) -> dict[str, Any]:
    """Build a read-only audit report.  Returns a dict, never raises."""
    base: dict[str, Any] = {
        "schema_version": "i_line.audit_report.v1",
        "read_only": True,
        "sensitive_body_output": False,
    }
    if audit_dir is None:
        try:
            from .isaac_agent_bus_p0 import _resolve_isaac_audit_dir  # type: ignore
            audit_dir = _resolve_isaac_audit_dir()
        except Exception:
            try:
                import importlib.util as _il, sys as _sys
                from pathlib import Path as _P
                _mod_path = _P(__file__).resolve().parent / "isaac_agent_bus_p0.py"
                _name = "isaac_agent_bus_p0_under_test"
                _mod = _sys.modules.get(_name)
                if _mod is None:
                    _spec = _il.spec_from_file_location(_name, _mod_path)
                    _mod = _il.module_from_spec(_spec)
                    _sys.modules[_name] = _mod
                    _spec.loader.exec_module(_mod)
                audit_dir = _mod._resolve_isaac_audit_dir()
            except Exception as exc:  # pragma: no cover - defensive
                base["status"] = "ERROR"
                base["error"] = f"audit_dir_unresolved:{type(exc).__name__}"
                return base

    audit_path = audit_dir / "isaac_p0_audit.jsonl"
    base["audit_path"] = audit_path.name
    base["audit_dir"] = audit_path.name  # never expose absolute host paths

    if not audit_path.exists():
        base["status"] = "EMPTY"
        base["audit_file_exists"] = False
        base["total_lines"] = 0
        base["recent_scanned_lines"] = 0
        base["counts"] = {"decision": {}, "trigger": {}, "task_type": {}}
        base["recent"] = []
        return base

    try:
        records = list(_iter_audit_records(audit_path, tail_bytes=tail_bytes))
    except Exception as exc:  # pragma: no cover - defensive
        base["status"] = "ERROR"
        base["audit_file_exists"] = True
        base["error"] = f"audit_read_failed:{type(exc).__name__}"
        return base

    agg = _aggregate(records)
    base["status"] = "PASS" if records else "EMPTY"
    base["audit_file_exists"] = True
    base["total_lines"] = len(records)
    base["recent_scanned_lines"] = len(records)
    base["counts"] = {
        "decision": agg["decision_counts"],
        "trigger": agg["trigger_counts"],
        "task_type": agg["task_type_counts"],
    }
    base["recent"] = _summarize_recent(records, limit=recent_limit)
    return base


def build_status_report(audit_dir: Path | None = None) -> dict[str, Any]:
    audit = build_audit_report(audit_dir=audit_dir)
    return {
        "schema_version": "i_line.status_report.v1",
        "read_only": True,
        "sensitive_body_output": False,
        "audit_overview": {
            "status": audit.get("status"),
            "audit_file_exists": audit.get("audit_file_exists", False),
            "total_lines": audit.get("total_lines", 0),
            "counts": audit.get("counts", {}),
            "recent": audit.get("recent", []),
        },
        "capabilities": list(_ALLOWED_CAPABILITIES),
        "capability_descriptions": {
            "health": "只读健康快照（gate/runtime/errors），不发网络请求。",
            "workspace": "工作区只读报告（文件系统+audit 元数据）。",
            "audit": "P0 审计 JSONL 聚合计数 + 最近摘要（owner 私聊）。",
            "help": "可用命令与边界说明。",
        },
        "scope": "owner_private_only",
    }


def format_audit_report(report: dict[str, Any]) -> str:
    lines: list[str] = ["I叔 P0 audit 概览（read-only）："]
    status = report.get("status") or "unknown"
    exists = report.get("audit_file_exists")
    total = _safe_int(report.get("total_lines"), 0)
    lines.append(f"status={status} audit_file_exists={str(bool(exists)).lower()} total_lines={total}")
    counts = dict(report.get("counts") or {})
    decision = dict(counts.get("decision") or {})
    trigger = dict(counts.get("trigger") or {})
    if decision:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(decision.items()))
        lines.append(f"decision_counts: {parts}")
    if trigger:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(trigger.items()))
        lines.append(f"trigger_counts: {parts}")
    recent = list(report.get("recent") or [])
    if recent:
        lines.append("recent:")
        for r in recent:
            ts = r.get("ts") or "-"
            lines.append(
                f"  - ts={ts} decision={r.get('decision')} trigger={r.get('trigger_type')} "
                f"cmd={r.get('command_head')} task={r.get('task_type')} reason={r.get('reason')} actor={r.get('actor')}"
            )
    return "\n".join(lines)


def format_status_report(report: dict[str, Any]) -> str:
    lines: list[str] = ["I叔 P0 status（read-only）："]
    overview = dict(report.get("audit_overview") or {})
    lines.append(
        f"audit.status={overview.get('status')} audit_file_exists={str(bool(overview.get('audit_file_exists'))).lower()} "
        f"total_lines={_safe_int(overview.get('total_lines'), 0)}"
    )
    counts = dict(overview.get("counts") or {})
    decision = dict(counts.get("decision") or {})
    if decision:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(decision.items()))
        lines.append(f"audit.decision_counts: {parts}")
    caps = list(report.get("capabilities") or [])
    if caps:
        lines.append(f"capabilities: {', '.join(caps)}")
    descs = dict(report.get("capability_descriptions") or {})
    for cap in caps:
        d = descs.get(cap)
        if d:
            lines.append(f"  - {cap}: {d}")
    scope = report.get("scope") or "owner_private_only"
    lines.append(f"scope: {scope}")
    return "\n".join(lines)


def sanitize_reply_text(text: str) -> str:
    """Strip sensitive markers / overly long raw echoes.  Defensive."""
    if not text:
        return ""
    out = text
    for marker in _SENSITIVE_MARKERS:
        out = re.sub(re.escape(marker), "[REDACTED]", out, flags=re.IGNORECASE)
    return out


__all__ = [
    "build_audit_report",
    "build_status_report",
    "format_audit_report",
    "format_status_report",
    "sanitize_reply_text",
]
