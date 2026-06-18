#!/usr/bin/env python3
"""I叔 Agent v0.1 wiring tests.

Pins the minimum-bleed contract from the v0.1 wiring ticket:
  - model_router.call_via_tier survives 2-tuple returns from self.call().
  - handle_isaac_agent_bus_p0_message is reachable from owner private chat
    and routes through the IsaacAgent decision layer (mocked).
  - Group / non-owner remain locked.
  - Agent decisions for health/status/workspace/audit/dry_run_plan map to the
    existing P0 built-in worker.
  - LLM picks of restart/shell/write never execute: they fall through to
    forbidden/unsupported.

Run: cd /opt/yangyang_nonebot && python3 -m pytest tests/test_isaac_agent_v0_wiring.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
PLUGIN_ROOT = SRC_ROOT / "plugins" / "yangyang"
CORE_PATH = PLUGIN_ROOT / "core"
AGENT_DIR = CORE_PATH / "isaac_agent"

# Reuse the repo's test infra for nonebot stubs + module loading.
from mock_pipeline_runtime import (  # type: ignore
    install_nonebot_stubs,
    ensure_package,
    load_module,
)

install_nonebot_stubs()
ensure_package("plugins", SRC_ROOT / "plugins")
ensure_package("plugins.yangyang", PLUGIN_ROOT)
ensure_package("plugins.yangyang.core", PLUGIN_ROOT / "core")
ensure_package("plugins.yangyang.core.model", PLUGIN_ROOT / "core" / "model")
ensure_package("plugins.yangyang.core.isaac_agent", PLUGIN_ROOT / "core" / "isaac_agent")

provider_mock_mod = load_module(
    "plugins.yangyang.core.model.provider_mock",
    PLUGIN_ROOT / "core" / "model" / "provider_mock.py",
)
load_module("plugins.yangyang.core.model.provider_base", PLUGIN_ROOT / "core" / "model" / "provider_base.py")
load_module("plugins.yangyang.core.model.provider_deepseek", PLUGIN_ROOT / "core" / "model" / "provider_deepseek.py")
load_module("plugins.yangyang.core.model.provider_minimax", PLUGIN_ROOT / "core" / "model" / "provider_minimax.py")
load_module("plugins.yangyang.core.model.provider_openai_compat", PLUGIN_ROOT / "core" / "model" / "provider_openai_compat.py")
load_module("plugins.yangyang.core.model.provider_anthropic", PLUGIN_ROOT / "core" / "model" / "provider_anthropic.py")
load_module("plugins.yangyang.core.token_usage", PLUGIN_ROOT / "core" / "token_usage.py")
load_module("plugins.yangyang.core.model_profile_switcher", PLUGIN_ROOT / "core" / "model_profile_switcher.py")
load_module("plugins.yangyang.core.runtime_compat", PLUGIN_ROOT / "core" / "runtime_compat.py")
load_module("plugins.yangyang.core.isaac_intent_p1", PLUGIN_ROOT / "core" / "isaac_intent_p1.py")
load_module("plugins.yangyang.core.isaac_dry_run_plan", PLUGIN_ROOT / "core" / "isaac_dry_run_plan.py")
load_module("plugins.yangyang.core.isaac_readonly_health", PLUGIN_ROOT / "core" / "isaac_readonly_health.py")
load_module("plugins.yangyang.core.isaac_audit_report", PLUGIN_ROOT / "core" / "isaac_audit_report.py")
load_module("plugins.yangyang.core.isaac_workspace_report", PLUGIN_ROOT / "core" / "isaac_workspace_report.py")
load_module("plugins.yangyang.core.isaac_agentbus_factory_report", PLUGIN_ROOT / "core" / "isaac_agentbus_factory_report.py")
agent_v0_mod = load_module(
    "plugins.yangyang.core.isaac_agent.agent_v0",
    PLUGIN_ROOT / "core" / "isaac_agent" / "agent_v0.py",
)
router_mod = load_module("plugins.yangyang.core.model_router", PLUGIN_ROOT / "core" / "model_router.py")
bus = load_module("plugins.yangyang.core.isaac_agent_bus_p0", PLUGIN_ROOT / "core" / "isaac_agent_bus_p0.py")

ModelRouter = router_mod.ModelRouter
IsaacAgent = agent_v0_mod.IsaacAgent


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_router(response_text: str = "ok-from-fake"):
    router = ModelRouter(runtime_cfg=None)
    # MockProvider 的 provider_name 固定是 "mock"；把 v4_pro / v4_flash 的
    # provider 字段在 TIERS 之外指到 "mock" 并 enable 起来，才能让 router 命中。
    fake = provider_mock_mod.MockProvider(response_text=response_text)
    router.providers["mock"] = fake
    router.TIERS["v4_pro"] = dict(router.TIERS["v4_pro"], provider="mock", enabled=True)
    router.TIERS["v4_flash"] = dict(router.TIERS["v4_flash"], provider="mock", enabled=True)
    return router


def _make_owner_private_msg(text: str = "/i叔 health"):
    return SimpleNamespace(
        text=text,
        raw_content=text,
        channel="private",
        is_owner=True,
        user_id="owner-hash-1234",
        uid="owner-hash-1234",
        explicit_command=True,
    )


def _make_non_owner_msg(text: str = "/i叔 health"):
    return SimpleNamespace(
        text=text,
        raw_content=text,
        channel="private",
        is_owner=False,
        user_id="intruder-9999",
        explicit_command=True,
    )


def _make_group_msg(text: str = "/i叔 health"):
    return SimpleNamespace(
        text=text,
        raw_content=text,
        channel="group",
        is_owner=True,
        user_id="owner-1",
        explicit_command=True,
    )


def _build_mock_agent(chosen: str | None, blocked: str = ""):
    agent = MagicMock()
    decision = SimpleNamespace(
        chosen_tool=chosen or "",
        blocked_reason=blocked,
        reason="mock-reason",
        tool_existed=bool(chosen),
    )
    agent.think.return_value = decision
    return agent


# ---------------------------------------------------------------------------
# 1) model_router.call_via_tier: 2-tuple compatibility
# ---------------------------------------------------------------------------

def test_call_via_tier_accepts_two_tuple():
    """self.call() returns (text, tier); call_via_tier must not ValueError."""
    router = _make_router("hello-2tuple")
    out = router.call_via_tier(
        tier="v4_pro",
        messages=[{"role": "user", "content": "ping"}],
        target_agent="isaac",
    )
    assert isinstance(out, dict)
    assert "content" in out
    assert "tier" in out
    assert out["content"] == "hello-2tuple"


def test_call_via_tier_accepts_three_tuple(monkeypatch):
    """Future-proof: if self.call ever returns 3-tuple, call_via_tier still works."""
    router = _make_router("never-used")

    async def fake_call(*_args, **_kw):
        return ("hello-3tuple", "v4_pro", [{"step": 1, "tool_name": "x"}])

    monkeypatch.setattr(router, "call", fake_call)
    out = router.call_via_tier(tier="v4_pro", messages=[{"role": "user", "content": "p"}])
    assert out["content"] == "hello-3tuple"
    assert out["tier"] == "v4_pro"


# ---------------------------------------------------------------------------
# 2) Bus P0 + IsaacAgent decision wiring
# ---------------------------------------------------------------------------

def test_bus_owner_private_reaches_isaac_agent_decision(tmp_path):
    """owner 私聊 + /i叔 health → IsaacAgent.think() 被调，落到 builtin worker。"""
    msg = _make_owner_private_msg("/i叔 health")
    mock_agent = _build_mock_agent(chosen="health")
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        result = bus.handle_isaac_agent_bus_p0_message(
            msg, model_router=MagicMock(), isaac_agent=None
        )
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == "health_report"
    assert mock_agent.think.called, "IsaacAgent.think must be invoked"
    call_kwargs = mock_agent.think.call_args.kwargs
    # Bus 应当把 command_text 作为 user_intent 喂给 agent。
    assert "user_intent" in call_kwargs
    assert call_kwargs["user_intent"].strip() == "health"


def test_bus_group_locked_even_when_agent_loaded():
    """群聊仍被 bus 自带的 channel gate 锁死。"""
    msg = _make_group_msg("/i叔 health")
    mock_agent = _build_mock_agent(chosen="health")
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        result = bus.handle_isaac_agent_bus_p0_message(
            msg, model_router=MagicMock()
        )
    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "private_only"
    assert not mock_agent.think.called


def test_bus_non_owner_locked_even_when_agent_loaded():
    msg = _make_non_owner_msg("/i叔 health")
    mock_agent = _build_mock_agent(chosen="health")
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        result = bus.handle_isaac_agent_bus_p0_message(
            msg, model_router=MagicMock()
        )
    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "owner_only"
    assert not mock_agent.think.called


@pytest.mark.parametrize(
    "agent_chosen,expected_task_type",
    [
        ("health", "health_report"),
        ("workspace", "workspace_report"),
        ("audit", "audit_report"),
        ("status", "status_report"),
        ("dry_run_plan", "dry_run_plan"),
        ("agentbus_factory", "agentbus_factory_report"),
    ],
)
def test_agent_decision_maps_to_p0_task_types(agent_chosen, expected_task_type):
    msg = SimpleNamespace(
        text="help",
        raw_content="help",
        channel="private",
        is_owner=True,
        user_id="owner-hash-1234",
        uid="owner-hash-1234",
        explicit_command=False,
        natural_llm_delegate=True,
    )
    mock_agent = _build_mock_agent(chosen=agent_chosen)
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        result = bus.handle_isaac_agent_bus_p0_message(
            msg, model_router=MagicMock()
        )
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == expected_task_type


def test_slash_explicit_task_type_is_not_overridden_by_agent_choice():
    msg = _make_owner_private_msg("/i叔 status")
    mock_agent = _build_mock_agent(chosen="health")
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        result = bus.handle_isaac_agent_bus_p0_message(
            msg, model_router=MagicMock()
        )
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == "status_report"
    assert mock_agent.think.called
    assert result.agent_audit is not None
    assert result.agent_audit["agent_chosen_tool"] == "health"


@pytest.mark.parametrize(
    "agent_chosen,blocked",
    [
        ("restart", ""),
        ("shell_run", ""),
        ("write_file", ""),
        ("delete_file", ""),
        ("deploy_service", ""),
        ("", "forbidden_tool_requested: restart"),
        ("nonexistent", "tool_not_in_registry: nonexistent"),
    ],
)
def test_forbidden_or_unknown_agent_choice_does_not_execute(agent_chosen, blocked):
    """LLM 选了高危 / 未知工具时，bus 必须 fail-closed，不落到 builtin worker。"""
    msg = _make_owner_private_msg("/i叔 help")
    decision = SimpleNamespace(
        chosen_tool=agent_chosen,
        blocked_reason=blocked,
        reason="mock",
        tool_existed=False,
    )
    mock_agent = MagicMock()
    mock_agent.think.return_value = decision
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        result = bus.handle_isaac_agent_bus_p0_message(
            msg, model_router=MagicMock()
        )
    assert result.handled is True
    assert result.allowed is False
    # 任一阻断原因都应体现"agent 拒绝了 dispatch"这一事实。
    assert (
        "forbidden_or_unsupported_tool" in result.reason
        or "agent_tool_not_mapped" in result.reason
    )
    # 高危场景下 builtin worker 不得被调用（reply 不会带 "PASS"）。
    assert "PASS" not in (result.reply or "")


def test_agent_think_exception_falls_back_to_builtin_worker():
    """IsaacAgent.think 抛异常时，bus 仍能跑 builtin worker（fail-soft）。"""
    msg = _make_owner_private_msg("/i叔 help")
    mock_agent = MagicMock()
    mock_agent.think.side_effect = RuntimeError("LLM 爆了")
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        result = bus.handle_isaac_agent_bus_p0_message(
            msg, model_router=MagicMock()
        )
    # /i叔 help → help_report，agent 异常不阻塞
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == "help_report"


def test_agent_null_choice_on_explicit_slash_falls_back_to_builtin_worker():
    msg = _make_owner_private_msg("/i叔 help")
    decision = SimpleNamespace(
        chosen_tool="",
        blocked_reason="",
        reason="no readonly tool fits",
        tool_existed=False,
    )
    mock_agent = MagicMock()
    mock_agent.think.return_value = decision
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        result = bus.handle_isaac_agent_bus_p0_message(
            msg, model_router=MagicMock()
        )
    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "pass"
    assert result.task_type == "help_report"
    assert result.agent_audit is not None
    assert result.agent_audit["agent_reason"] == "agent_no_choice_fallback"


def test_agent_null_choice_on_natural_delegate_still_blocks_for_clarification():
    msg = _make_owner_private_natural_msg("让I叔看看这个自然语言请求")
    decision = SimpleNamespace(
        chosen_tool="",
        blocked_reason="",
        reason="no readonly tool fits",
        tool_existed=False,
    )
    mock_agent = MagicMock()
    mock_agent.think.return_value = decision
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        result = bus.handle_isaac_agent_bus_p0_message(
            msg, model_router=MagicMock()
        )
    assert result.handled is True
    assert result.allowed is False
    assert result.task_request is None
    assert result.reason in {"clarification_required", "agent_no_choice_fallback"}


def test_no_router_no_agent_keeps_existing_behavior():
    """没有 router / agent 时，bus 仍能跑 builtin worker（兼容旧调用方）。"""
    msg = _make_owner_private_msg("/i叔 help")
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=None):
        with patch.object(bus, "_resolve_available_router", return_value=None):
            result = bus.handle_isaac_agent_bus_p0_message(msg, model_router=None)
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == "help_report"


# ---------------------------------------------------------------------------
# 3) __init__.py wiring gate
# ---------------------------------------------------------------------------

def test_init_wiring_in_place():
    """__init__.py 实际包含 owner+private gate → handle_isaac_agent_bus_p0_message 的调用。"""
    init_src = (REPO_ROOT / "src" / "plugins" / "yangyang" / "__init__.py").read_text(encoding="utf-8")
    # 三个必备关键字：gate 条件、bus 调用、router 传入
    assert "handle_isaac_agent_bus_p0_message" in init_src
    assert 'is_owner' in init_src
    assert "channel" in init_src and '"private"' in init_src
    assert "model_router=router" in init_src


def test_init_gate_owner_private_slash_passes():
    msg = _make_owner_private_msg("/i叔 health")
    gate_ok = (
        bool(getattr(msg, "is_owner", False))
        and str(getattr(msg, "channel", "") or "") == "private"
        and bool(getattr(msg, "explicit_command", False))
    )
    assert gate_ok is True


def test_init_gate_group_refuses():
    msg = _make_group_msg("/i叔 health")
    gate_ok = (
        bool(getattr(msg, "is_owner", False))
        and str(getattr(msg, "channel", "") or "") == "private"
        and bool(getattr(msg, "explicit_command", False))
    )
    assert gate_ok is False


def test_init_gate_non_owner_refuses():
    msg = _make_non_owner_msg("/i叔 health")
    gate_ok = (
        bool(getattr(msg, "is_owner", False))
        and str(getattr(msg, "channel", "") or "") == "private"
        and bool(getattr(msg, "explicit_command", False))
    )
    assert gate_ok is False


if __name__ == "__main__":
    import pytest as _p

    raise SystemExit(_p.main([__file__, "-v"]))


def _make_owner_private_natural_msg(text: str):
    return SimpleNamespace(
        text=text,
        raw_content=text,
        channel="private",
        is_owner=True,
        user_id="owner-hash-1234",
        uid="owner-hash-1234",
        explicit_command=False,
        natural_llm_delegate=True,
    )


def test_natural_delegate_dry_run_continues_into_isaac_agent():
    """自然语言低风险 dry_run_plan 不应停在 P1 preview，必须先过 IsaacAgent。"""
    msg = _make_owner_private_natural_msg("让I叔帮我检查 Agent v0.1 接线，但不要执行任何修改，只给计划")
    mock_agent = _build_mock_agent(chosen="dry_run_plan")
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        result = bus.handle_isaac_agent_bus_p0_message(
            msg, model_router=MagicMock(), isaac_agent=None
        )
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == "dry_run_plan"
    assert result.reason == "pass"
    assert mock_agent.think.called
    assert result.agent_audit is not None
    assert result.agent_audit["agent_called"] is True
    assert result.agent_audit["agent_chosen_tool"] == "dry_run_plan"


def test_agent_audit_summary_written_for_success(monkeypatch, tmp_path):
    """P0 audit 必须能记录 agent_called/used_tier/chosen_tool，避免靠账单猜。"""
    records = []

    def fake_record(**kwargs):
        records.append(kwargs)

    msg = _make_owner_private_msg("/i叔 health")
    mock_agent = _build_mock_agent(chosen="health")
    with patch.object(bus, "_record_isaac_p0_audit", side_effect=fake_record):
        with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
            result = bus.handle_isaac_agent_bus_p0_message(msg, model_router=MagicMock())
    assert result.allowed is True
    assert records, "audit writer should be called"
    assert records[-1]["agent_audit"]["agent_called"] is True
    assert records[-1]["agent_audit"]["agent_chosen_tool"] == "health"
    assert records[-1]["agent_audit"].get("agent_used_tier") in ("v4_pro", "")



def test_owner_toolbox_async_isaac_p0_passes_model_router(monkeypatch):
    """owner toolbox native async path must forward model_router into I叔 Agent bus."""
    exec_mod = load_module(
        "plugins.yangyang.core.owner_toolbox.executor",
        PLUGIN_ROOT / "core" / "owner_toolbox" / "executor.py",
    )
    seen = {}

    def fake_handler(msg, **kwargs):
        seen["router"] = kwargs.get("model_router")
        return SimpleNamespace(
            handled=True,
            allowed=True,
            reason="pass",
            reply="ok",
            task_type="health_report",
        )

    monkeypatch.setattr(exec_mod, "handle_isaac_agent_bus_p0_message", fake_handler)
    router = MagicMock(name="router")
    import asyncio
    result = asyncio.run(exec_mod.execute_owner_toolbox_tool_async(
        "isaac_p0",
        {"command_text": "health", "_context_channel": "private", "_context_user_id": "owner-hash-1234"},
        config=None,
        model_router=router,
        context_channel="private",
    ))
    assert result.allowed is True
    assert seen["router"] is router


# ---------------------------------------------------------------------------
# 3) Explicit QQ smoke: /i叔 agent_ping
# ---------------------------------------------------------------------------

def test_agent_ping_owner_private_calls_agent_without_running_worker():
    msg = _make_owner_private_msg("/i叔 agent_ping 看看系统状态")
    mock_agent = _build_mock_agent(chosen="health")

    result = bus.handle_isaac_agent_bus_p0_message(
        msg, model_router=MagicMock(), isaac_agent=mock_agent
    )

    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "agent_ping_pass"
    assert result.task_type == "agent_ping"
    assert result.task_request is None
    assert result.task_result is None
    assert result.worker_result is None
    assert mock_agent.think.called
    assert mock_agent.think.call_args.kwargs["user_intent"] == "看看系统状态"
    assert "route=isaac_agent_v0" in result.reply
    assert "llm_called=true" in result.reply
    assert "chosen_tool=health" in result.reply
    assert "tool_executed=false" in result.reply
    assert result.agent_audit is not None
    assert result.agent_audit["route"] == "isaac_agent_v0"


def test_agent_ping_default_payload_when_empty():
    msg = _make_owner_private_msg("/i叔 agent_ping")
    mock_agent = _build_mock_agent(chosen="health")

    result = bus.handle_isaac_agent_bus_p0_message(
        msg, model_router=MagicMock(), isaac_agent=mock_agent
    )

    assert result.allowed is True
    assert mock_agent.think.call_args.kwargs["user_intent"] == "看看系统状态"



def test_agent_ping_null_choice_gets_visible_block_reason():
    msg = _make_owner_private_msg("/i叔 agent_ping 给珂老师唱首歌")
    mock_agent = _build_mock_agent(chosen=None, blocked="")

    result = bus.handle_isaac_agent_bus_p0_message(
        msg, model_router=MagicMock(), isaac_agent=mock_agent
    )

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "agent_ping_blocked"
    assert "chosen_tool=" in result.reply
    assert "blocked_reason=no_readonly_tool_chosen" in result.reply
    assert "tool_executed=false" in result.reply


def test_agent_ping_forbidden_llm_choice_is_visible_but_no_worker_runs():
    msg = _make_owner_private_msg("/i叔 agent_ping 帮我重启服务")
    mock_agent = _build_mock_agent(chosen="", blocked="forbidden_tool_requested: restart_service")

    result = bus.handle_isaac_agent_bus_p0_message(
        msg, model_router=MagicMock(), isaac_agent=mock_agent
    )

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "agent_ping_blocked"
    assert result.task_type == "agent_ping"
    assert result.task_request is None
    assert result.worker_result is None
    assert "route=isaac_agent_v0" in result.reply
    assert "llm_called=true" in result.reply
    assert "blocked_reason=forbidden_tool_requested: restart_service" in result.reply
    assert "tool_executed=false" in result.reply


def test_agent_ping_group_and_non_owner_still_locked():
    mock_agent = _build_mock_agent(chosen="health")

    group_result = bus.handle_isaac_agent_bus_p0_message(
        _make_group_msg("/i叔 agent_ping 看看系统"), model_router=MagicMock(), isaac_agent=mock_agent
    )
    assert group_result.handled is True
    assert group_result.allowed is False
    assert group_result.reason == "private_only"
    assert not mock_agent.think.called

    non_owner_result = bus.handle_isaac_agent_bus_p0_message(
        _make_non_owner_msg("/i叔 agent_ping 看看系统"), model_router=MagicMock(), isaac_agent=mock_agent
    )
    assert non_owner_result.handled is True
    assert non_owner_result.allowed is False
    assert non_owner_result.reason == "owner_only"
    assert not mock_agent.think.called


def test_agentbus_factory_report_uses_agent_readonly_tool_output():
    msg = _make_owner_private_msg("/i叔 agentbus factory")
    decision = SimpleNamespace(
        chosen_tool="agentbus_factory",
        blocked_reason="",
        reason="mock-reason",
        tool_existed=True,
        model_tier="v4_pro",
        tool_executed=True,
        tool_output={
            "schema_version": "i_line.agentbus_factory_report.v1",
            "read_only": True,
            "latest_run": {"name": "mock-run"},
        },
        tool_latency_ms=7,
        tool_blocked_reason="",
    )
    mock_agent = MagicMock()
    mock_agent.think.return_value = decision
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        with patch.object(bus, "_import_agentbus_factory_report_builder") as builtin_builder:
            result = bus.handle_isaac_agent_bus_p0_message(msg, model_router=MagicMock())
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == "agentbus_factory_report"
    assert result.worker_result["isaac_worker"] == "isaac_agent_v02_readonly_tool"
    assert result.worker_result["read_only"] is True
    diagnostics = result.worker_result["diagnostics"]
    assert diagnostics["agentbus_factory_check"] == "isaac_agent_v02_readonly_tool"
    assert diagnostics["agent_tool_executed"] is True
    report = diagnostics["agentbus_factory_report"]
    assert report["read_only"] is True
    assert report["latest_run"]["name"] == "mock-run"
    assert not builtin_builder.called
    assert "host_action_executed=false" in result.reply

@pytest.mark.parametrize(
    "decision_kwargs",
    [
        {"chosen_tool": "health", "tool_executed": True, "tool_output": {"read_only": True}},
        {"chosen_tool": "agentbus_factory", "tool_executed": False, "tool_output": {}},
    ],
)
def test_agentbus_factory_report_falls_back_to_builtin_when_agent_decision_not_executable(decision_kwargs):
    msg = _make_owner_private_msg("/i叔 agentbus factory")
    decision = SimpleNamespace(
        blocked_reason="",
        reason="mock-reason",
        tool_existed=True,
        model_tier="v4_pro",
        tool_latency_ms=0,
        tool_blocked_reason="",
        **decision_kwargs,
    )
    mock_agent = MagicMock()
    mock_agent.think.return_value = decision
    fake_report = {
        "schema_version": "i_line.agentbus_factory_report.v1",
        "read_only": True,
        "latest_run": {"name": "fallback-run"},
    }
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        with patch.object(bus, "_import_agentbus_factory_report_builder", return_value=lambda: fake_report) as builtin_builder:
            result = bus.handle_isaac_agent_bus_p0_message(msg, model_router=MagicMock())
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == "agentbus_factory_report"
    assert result.worker_result["isaac_worker"] == "isaac_builtin_readonly_p0"
    assert result.worker_result["diagnostics"]["agentbus_factory_check"] == "readonly_latest_run_v1"
    assert result.worker_result["diagnostics"]["agentbus_factory_report"]["latest_run"]["name"] == "fallback-run"
    assert builtin_builder.called


def test_agentbus_factory_report_falls_back_to_builtin_when_agent_unavailable():
    msg = _make_owner_private_msg("/i叔 agentbus factory")
    fake_report = {
        "schema_version": "i_line.agentbus_factory_report.v1",
        "read_only": True,
        "latest_run": {"name": "agent-unavailable-fallback"},
    }
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=None):
        with patch.object(bus, "_import_agentbus_factory_report_builder", return_value=lambda: fake_report) as builtin_builder:
            result = bus.handle_isaac_agent_bus_p0_message(msg, model_router=MagicMock())
    assert result.handled is True
    assert result.allowed is True
    assert result.worker_result["isaac_worker"] == "isaac_builtin_readonly_p0"
    assert result.worker_result["diagnostics"]["agentbus_factory_report"]["latest_run"]["name"] == "agent-unavailable-fallback"
    assert builtin_builder.called


def test_agentbus_factory_report_wraps_non_dict_agent_tool_output():
    msg = _make_owner_private_msg("/i叔 agentbus factory")
    decision = SimpleNamespace(
        chosen_tool="agentbus_factory",
        blocked_reason="",
        reason="mock-reason",
        tool_existed=True,
        model_tier="v4_pro",
        tool_executed=True,
        tool_output=["not", "a", "dict"],
        tool_latency_ms=3,
        tool_blocked_reason="",
    )
    mock_agent = MagicMock()
    mock_agent.think.return_value = decision
    with patch.object(bus, "_build_isaac_agent_for_bus", return_value=mock_agent):
        result = bus.handle_isaac_agent_bus_p0_message(msg, model_router=MagicMock())
    assert result.handled is True
    assert result.allowed is True
    assert result.worker_result["isaac_worker"] == "isaac_agent_v02_readonly_tool"
    assert result.worker_result["provider_network_used"] is False
    assert result.worker_result["diagnostics"]["agentbus_factory_report"] == {"status": "non_dict_tool_output"}


def test_non_agentbus_factory_tasks_never_take_agent_executed_path():
    decision = SimpleNamespace(
        chosen_tool="agentbus_factory",
        tool_executed=True,
        tool_output={"read_only": True},
    )
    verdict = {"decision": decision}
    assert bus._build_agent_executed_worker_result("health_report", verdict, {"envelope": {}}) is None

