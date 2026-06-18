from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_intent_p1.py"
SPEC = importlib.util.spec_from_file_location("isaac_intent_p1_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)
parse_intent_dry_run = mod.parse_intent_dry_run


def test_p1_health_intent_would_dispatch_dry_run_only() -> None:
    d = parse_intent_dry_run("麻烦 I叔 看看你现在状态")
    assert d.handled is True
    assert d.allowed is True
    assert d.decision == "would_dispatch_dry_run"
    assert d.would_dispatch_task_type == "health_report"
    assert d.candidate is not None and d.candidate.intent == "health_report"
    assert "不真实派发" in d.reply


def test_p1_english_isaac_does_not_trigger() -> None:
    d = parse_intent_dry_run("isaac 看看状态")
    assert d.handled is False
    assert d.decision == "not_triggered"


def test_p1_ambiguous_requires_clarification() -> None:
    d = parse_intent_dry_run("I叔 你看这个是不是有问题？")
    assert d.handled is True
    assert d.allowed is False
    assert d.decision == "clarification_required"
    assert d.would_dispatch_task_type is None


def test_p1_high_risk_blocks_before_dispatch() -> None:
    d = parse_intent_dry_run("I叔 帮我重启服务")
    assert d.handled is True
    assert d.allowed is False
    assert d.decision == "blocked"
    assert d.reason == "high_risk_blocked"
    assert d.would_dispatch_task_type is None


def test_p1_workspace_and_plan_are_allowlisted() -> None:
    workspace = parse_intent_dry_run("艾萨克 做个 workspace report")
    plan = parse_intent_dry_run("I叔 做个 dry_run plan")
    assert workspace.allowed and workspace.would_dispatch_task_type == "workspace_report"
    assert plan.allowed and plan.would_dispatch_task_type == "dry_run_plan"
