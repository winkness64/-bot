from __future__ import annotations

import hashlib
import re
from typing import Any

HIGH_RISK_TOKENS = (
    "restart", "systemctl", "deploy", "release", "rollback",
    ".env", "key", "token", "secret", "password", "passwd",
    "authorization", "cookie", "base_url",
    "runtime_config", "memories", "long_term",
)

CATEGORY_RULES = (
    ("audit", ("audit", "审计", "审计报告", "audit_report")),
    ("status", ("status", "状态", "情况", "总览", "面板")),
    ("health", ("health", "selfcheck", "check", "健康", "自检", "诊断", "巡检", "异常", "报错")),
    ("workspace", ("workspace", "workspacereport", "工作区", "项目状态")),
    ("model", ("model", "模型", "provider", "llm", "切换模型")),
    ("toolbox", ("toolbox", "工具箱", "owner_toolbox", "工具")),
    ("memory", ("memory", "记忆", "长期记忆", "memories", "long_term")),
    ("config", ("config", "配置", "runtime_config", ".env")),
    ("restart", ("restart", "重启", "systemctl", "reload", "systemd")),
    ("deploy", ("deploy", "部署", "发布", "release", "rollback", "回滚")),
)

LIKELY_FILES_BY_CATEGORY = {
    "audit": ["src/plugins/yangyang/core/isaac_audit_report.py", "src/plugins/yangyang/core/isaac_agent_bus_p0.py"],
    "status": ["src/plugins/yangyang/core/isaac_agent_bus_p0.py", "src/plugins/yangyang/core/isaac_audit_report.py"],
    "health": ["src/plugins/yangyang/core/isaac_readonly_health.py", "src/plugins/yangyang/core/isaac_agent_bus_p0.py"],
    "workspace": ["src/plugins/yangyang/core/isaac_workspace_report.py", "src/plugins/yangyang/core/isaac_agent_bus_p0.py"],
    "model": ["src/plugins/yangyang/core/isaac_intent_provider_bridge_p15.py"],
    "toolbox": ["src/plugins/yangyang/core/isaac_agent_bus_p0.py"],
    "memory": ["src/plugins/yangyang/core/isaac_agent_bus_p0.py"],
    "config": ["src/plugins/yangyang/core/isaac_agent_bus_p0.py"],
    "restart": ["src/plugins/yangyang/core/isaac_agent_bus_p0.py"],
    "deploy": ["src/plugins/yangyang/core/isaac_agent_bus_p0.py"],
    "plan": ["src/plugins/yangyang/core/isaac_agent_bus_p0.py", "src/plugins/yangyang/core/isaac_dry_run_plan.py"],
}

TESTS_BY_CATEGORY = {
    "audit": ["tests/test_isaac_p0_audit.py", "tests/test_isaac_p0_audit_status.py"],
    "status": ["tests/test_isaac_p0_audit_status.py"],
    "health": ["tests/test_i_line_p0_isaac_agent_bus_mvp.py"],
    "workspace": ["tests/test_isaac_p0_workspace_report.py"],
    "plan": ["tests/test_isaac_p0_dry_run_plan.py"],
}

STEPS_TEMPLATE = {
    "audit": ["read isaac_p0_audit.jsonl tail", "summarize counters by task_type", "render compact audit block"],
    "status": ["read audit + capability gate snapshot", "merge counters", "render status block"],
    "health": ["build readonly health snapshot", "render 5-line compact block"],
    "workspace": ["scan workspace metadata", "render workspace report"],
    "model": ["inspect bridge config (read-only)", "no write"],
    "toolbox": ["inspect toolbox map (read-only)", "no write"],
    "memory": ["memory writes blocked at P0", "return blocked plan"],
    "config": ["config writes blocked at P0", "return blocked plan"],
    "restart": ["service control blocked at P0", "return blocked plan"],
    "deploy": ["deploy blocked at P0", "return blocked plan"],
    "plan": ["classify request", "build readonly plan", "render plan block"],
}


def _classify(need: str) -> list[str]:
    compact = re.sub(r"\s+", "", str(need or "").lower())
    hits: list[str] = []
    for name, tokens in CATEGORY_RULES:
        if any(tok in compact for tok in tokens):
            if name not in hits:
                hits.append(name)
    if not hits:
        hits.append("plan")
    return hits


def _detect_high_risk(need: str) -> list[str]:
    compact = re.sub(r"\s+", "", str(need or "").lower())
    out: list[str] = []
    for tok in HIGH_RISK_TOKENS:
        if tok in compact:
            out.append(tok)
    return out


def _hash_need(need: str) -> str:
    return hashlib.sha256(str(need or "").encode("utf-8")).hexdigest()[:16]


def build_dry_run_plan(need: str = "") -> dict[str, Any]:
    raw = str(need or "").strip()
    cats = _classify(raw)
    high = _detect_high_risk(raw)
    blocked_cats = [c for c in cats if c in {"restart", "deploy", "memory", "config"}]
    risk_level = "high" if (high or blocked_cats) else ("low" if cats == ["plan"] else "medium")

    likely_files: list[str] = []
    tests: list[str] = []
    steps: list[str] = []
    for c in cats:
        for f in LIKELY_FILES_BY_CATEGORY.get(c, []):
            if f not in likely_files:
                likely_files.append(f)
        for t in TESTS_BY_CATEGORY.get(c, []):
            if t not in tests:
                tests.append(t)
        for s in STEPS_TEMPLATE.get(c, []):
            if s not in steps:
                steps.append(s)

    if not raw:
        task_summary = "owner requested an empty dry_run plan; default low-risk plan scaffold"
        needs_owner_confirmation = False
        will_execute = False
        will_write_files = False
        will_restart_service = False
        blocked_reason: str | None = None
    elif risk_level == "high":
        task_summary = f"high-risk request covering: {','.join(cats)}"
        needs_owner_confirmation = True
        will_execute = False
        will_write_files = False
        will_restart_service = False
        blocked_reason = "high_risk_markers_present: " + ",".join(high or blocked_cats)
    else:
        task_summary = f"low/medium-risk request covering: {','.join(cats)}"
        needs_owner_confirmation = False
        will_execute = False
        will_write_files = False
        will_restart_service = False
        blocked_reason = None

    return {
        "status": "BLOCKED" if risk_level == "high" else "OK",
        "task_summary": task_summary,
        "risk_level": risk_level,
        "categories": cats,
        "high_risk_tokens": high,
        "blocked_reason": blocked_reason,
        "likely_files": likely_files,
        "steps": steps,
        "tests": tests,
        "needs_owner_confirmation": needs_owner_confirmation,
        "will_execute": will_execute,
        "will_write_files": will_write_files,
        "will_restart_service": will_restart_service,
        "need_hash": _hash_need(raw),
        "schema_version": "i_line.p0.dry_run_plan.v1",
    }
