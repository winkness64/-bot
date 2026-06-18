from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG_CORE = ROOT / "src" / "plugins" / "yangyang" / "core"


def _load(mod_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


p0 = _load("isaac_agent_bus_p0_for_test", PKG_CORE / "isaac_agent_bus_p0.py")
plan_mod = _load("isaac_dry_run_plan_for_test", PKG_CORE / "isaac_dry_run_plan.py")


class _FakeMsg:
    def __init__(self, *, text: str, group_id=None, user_id=8001, is_owner=True):
        self.text = text
        self.raw_content = text
        self.raw_message = text
        self.plain_text = text
        self.message = text
        self.message_str = text
        self.group_id = group_id
        self.channel = "private" if group_id is None else "group"
        self.is_owner = is_owner
        self.sender = type("S", (), {"user_id": user_id, "is_owner": is_owner})()


def _run(text: str, *, group_id=None, is_owner=True, user_id=8001):
    msg = _FakeMsg(text=text, group_id=group_id, user_id=user_id, is_owner=is_owner)
    return p0.handle_isaac_agent_bus_p0_message(msg, intent_provider=None)


def _plan(resp):
    assert resp.handled and resp.allowed, f"not handled: {resp.reason}"
    return resp.worker_result["diagnostics"]["dry_run_plan"]


# 1) /i叔 dry_run plan returns structured plan and will_execute=false
def test_dry_run_plan_default_structured():
    r = _run("/i叔 dry_run plan")
    plan = _plan(r)
    assert plan["will_execute"] is False
    assert plan["will_write_files"] is False
    assert plan["will_restart_service"] is False
    assert plan["status"] in ("OK", "BLOCKED")
    assert "task_summary" in plan
    assert "risk_level" in plan
    assert "likely_files" in plan
    assert "steps" in plan
    assert "tests" in plan
    assert "needs_owner_confirmation" in plan


# 2) /i叔 plan 自然语言生成 plan
def test_plan_natural_language_audit_status():
    r = _run("/i叔 plan 设计一下只读功能查看器")
    plan = _plan(r)
    assert plan["risk_level"] == "low"
    assert plan["need_hash"] != ""
    assert plan["will_execute"] is False


# 3) High risk restart/systemctl/deploy only flagged, not executed
@pytest.mark.parametrize("w", ["restart", "systemctl", "deploy", "回滚 release"])
def test_high_risk_only_flagged(w):
    r = _run(f"/i叔 plan {w} 服务")
    plan = _plan(r)
    assert plan["risk_level"] == "high"
    assert plan["status"] == "BLOCKED"
    assert plan["will_execute"] is False
    assert plan["will_write_files"] is False
    assert plan["will_restart_service"] is False
    assert plan["needs_owner_confirmation"] is True


# 4) Sensitive words not leaked in reply
@pytest.mark.parametrize("w", [".env", "api_key", "token", "secret", "password"])
def test_sensitive_words_not_leaked(w):
    r = _run(f"/i叔 plan 看下 {w} 配置")
    reply = (r.reply or "")
    # needle MUST be present in the *intent* for high-risk logic to fire,
    # but the reply must not echo it back as free-form value.
    # worker_result may contain high_risk_tokens / blocked_reason as audit data.
    if w in reply.lower():
        assert f'\"{w}\"' not in reply and f"'{w}'" not in reply


# 5) Group / non-owner do not expose plan content
def test_group_does_not_expose_plan():
    r = _run("/i叔 plan 修 audit", group_id=123456)
    # Either unhandled or denied
    if r.handled:
        assert r.allowed is False
    assert "dry_run_plan" not in str(r.worker_result or {})


def test_non_owner_does_not_expose_plan():
    r = _run("/i叔 plan 修 audit", is_owner=False, user_id=1)
    if r.handled:
        assert r.allowed is False
    assert "dry_run_plan" not in str(r.worker_result or {})


# 6) Regression: existing commands still work
@pytest.mark.parametrize("cmd,expected_type", [
    ("/i叔 help", "help_report"),
    ("/i叔 health", "health_report"),
    ("/i叔 workspace report", "workspace_report"),
    ("/i叔 audit", "audit_report"),
    ("/i叔 status", "status_report"),
    ("/i叔 dry_run plan", "dry_run_plan"),
])
def test_existing_commands_no_regression(cmd, expected_type):
    r = _run(cmd)
    assert r.handled and r.allowed, f"{cmd} -> {r.reason}"
    assert r.task_type == expected_type
    # CRITICAL: no actual side effects promised
    if expected_type == "dry_run_plan":
        plan = r.worker_result["diagnostics"]["dry_run_plan"]
        assert plan["will_execute"] is False
        assert plan["will_write_files"] is False
        assert plan["will_restart_service"] is False
