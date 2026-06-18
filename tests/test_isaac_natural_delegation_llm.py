"""小票5：Isaac natural LLM delegation 闭环回归。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mock_pipeline_runtime import DictConfig, install_nonebot_stubs, ensure_package, load_module  # type: ignore
from mock_pipeline_runtime import SRC_ROOT, PLUGIN_ROOT  # type: ignore

import pytest

install_nonebot_stubs()
ensure_package("plugins", SRC_ROOT / "plugins")
ensure_package("plugins.yangyang", PLUGIN_ROOT)
ensure_package("plugins.yangyang.core", PLUGIN_ROOT / "core")
ensure_package("plugins.yangyang.core.model", PLUGIN_ROOT / "core" / "model")

load_module("plugins.yangyang.core.model.provider_base", PLUGIN_ROOT / "core" / "model" / "provider_base.py")
load_module("plugins.yangyang.core.model.provider_deepseek", PLUGIN_ROOT / "core" / "model" / "provider_deepseek.py")
load_module("plugins.yangyang.core.model.provider_minimax", PLUGIN_ROOT / "core" / "model" / "provider_minimax.py")
provider_mock_mod = load_module("plugins.yangyang.core.model.provider_mock", PLUGIN_ROOT / "core" / "model" / "provider_mock.py")
router_mod = load_module("plugins.yangyang.core.model_router", PLUGIN_ROOT / "core" / "model_router.py")
light_mod = load_module("plugins.yangyang.core.owner_toolbox_light", PLUGIN_ROOT / "core" / "owner_toolbox_light.py")
p0_mod = load_module("plugins.yangyang.core.isaac_agent_bus_p0", PLUGIN_ROOT / "core" / "isaac_agent_bus_p0.py")
exec_mod = load_module("plugins.yangyang.core.owner_toolbox.executor", PLUGIN_ROOT / "core" / "owner_toolbox" / "executor.py")

MockProvider = provider_mock_mod.MockProvider
ModelRouter = router_mod.ModelRouter
handle_owner_toolbox_light_llm_message = light_mod.handle_owner_toolbox_light_llm_message
handle_owner_toolbox_light_message = light_mod.handle_owner_toolbox_light_message
_classify_isaac_trigger = p0_mod._classify_isaac_trigger
handle_isaac_agent_bus_p0_message = p0_mod.handle_isaac_agent_bus_p0_message
_resolve_isaac_audit_dir = p0_mod._resolve_isaac_audit_dir

OWNER_UID = "335059272"
SENSITIVE_MARKERS = (
    "api_key", "token", "base_url", "env", "secret", "password",
    "authorization", "cookie",
)


def _cfg(tmp_path: Path) -> DictConfig:
    return DictConfig({
        "owner_uid": OWNER_UID,
        "owner_uids": [OWNER_UID],
        "owner_toolbox_light_workspace_root": str(tmp_path),
        "owner_toolbox_light_timeout_seconds": 5,
        "owner_toolbox_light_max_output_chars": 4000,
        "owner_toolbox_light_native_loop_enabled": True,
        "owner_toolbox_light_plan_only_gate_enabled": False,
        "models": {"v4_flash": {"enabled": True, "model": "mock-model"}},
        "providers": {"v4_flash": {"enabled": True, "provider": "mock", "model": "mock-model", "timeout": 5, "cooldown_on_fail": 1}},
        "dry_run": False,
    })


def _msg(text: str, *, uid: str = OWNER_UID, channel: str = "private", is_owner=None):
    return SimpleNamespace(
        text=text, raw_content=text,
        uid=uid, user_id=uid,
        channel=channel,
        group_id="137918147" if channel == "group" else "",
        is_owner=(uid == OWNER_UID if is_owner is None else is_owner),
    )


def _router(cfg, responses):
    router = ModelRouter(cfg)
    router.register_provider(MockProvider(responses=responses))
    return router


def _run(coro):
    return asyncio.run(coro)


# ---------- 1) P0 direct bare text not regex-triggered ----------

def test_p0_bare_text_not_regex_triggered(tmp_path, monkeypatch):
    monkeypatch.setattr(p0_mod, "_resolve_isaac_audit_dir", lambda: tmp_path)
    # 分类器：纯自然文本 → natural_llm
    trig, _ = _classify_isaac_trigger("I叔 帮我看 workspace")
    assert trig == "natural_llm"
    # direct handler 不带 / 前缀 → handled=False（被忽略，不被 regex 抢走）
    msg = SimpleNamespace(
        text="I叔 帮我看 workspace",
        raw_content="I叔 帮我看 workspace",
        channel="private",
        is_owner=True,
        uid=OWNER_UID, user_id=OWNER_UID,
        group_id="",
    )
    result = handle_isaac_agent_bus_p0_message(msg)
    assert result.handled is False
    audit_path = tmp_path / "isaac_p0_audit.jsonl"
    if audit_path.exists():
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            assert row.get("trigger_type") == "natural_llm"


# ---------- 2) owner private NL + fake model tool_call isaac_p0 ----------

def _mock_agent(chosen: str):
    agent = MagicMock()
    agent.think.return_value = SimpleNamespace(
        chosen_tool=chosen,
        blocked_reason="",
        reason="mock",
        tool_existed=True,
        model_tier="v4_pro",
    )
    return agent


def test_owner_private_nl_tool_call_isaac_p0_workspace_requires_agent_endorsement(tmp_path, monkeypatch):
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(p0_mod, "_resolve_isaac_audit_dir", lambda: tmp_path)
    cfg = _cfg(tmp_path)
    router = _router(cfg, [
        {"content": "", "tool_calls": [{"id": "c1", "name": "isaac_p0", "arguments": {"command_text": "workspace report"}}]},
        "I叔 workspace 已查询。",
    ])
    result = _run(handle_owner_toolbox_light_llm_message(_msg("艾萨克 帮我看下 workspace"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert "isaac_p0" in [item.get("tool_name") for item in (result.raw_trace or [])]
    audit_path = tmp_path / "isaac_p0_audit.jsonl"
    rows = [json.loads(l) for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(
        r.get("trigger_type") == "natural_llm"
        and r.get("decision") == "denied"
        for r in rows
    )


def test_owner_private_tool_call_isaac_p0_workspace_with_agent_endorsement(tmp_path, monkeypatch):
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(p0_mod, "_resolve_isaac_audit_dir", lambda: tmp_path)
    cfg = _cfg(tmp_path)

    def endorsed_handler(msg, **kwargs):
        return p0_mod.handle_isaac_agent_bus_p0_message(
            msg, isaac_agent=_mock_agent("workspace"), **kwargs
        )

    with patch.object(exec_mod, "handle_isaac_agent_bus_p0_message", endorsed_handler):
        result = _run(exec_mod.execute_owner_toolbox_tool_async(
            "isaac_p0",
            {"command_text": "workspace report", "_context_channel": "private", "_context_user_id": OWNER_UID},
            cfg,
            model_router=MagicMock(),
            context_channel="private",
        ))
    assert result.handled is True
    assert result.allowed is True
    rows = [json.loads(l) for l in (tmp_path / "isaac_p0_audit.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(
        r.get("trigger_type") == "natural_llm"
        and r.get("decision") == "handled"
        and r.get("task_type") == "workspace_report"
        and r.get("agent_chosen_tool") == "workspace"
        for r in rows
    )


def test_owner_private_nl_tool_call_isaac_p0_health_requires_agent_endorsement(tmp_path, monkeypatch):
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(p0_mod, "_resolve_isaac_audit_dir", lambda: tmp_path)
    cfg = _cfg(tmp_path)
    router = _router(cfg, [
        {"content": "", "tool_calls": [{"id": "c1", "name": "isaac_p0", "arguments": {"command_text": "health"}}]},
        "I叔只读健康检查完成。",
    ])
    result = _run(handle_owner_toolbox_light_llm_message(_msg("I叔 health"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert "isaac_p0" in [item.get("tool_name") for item in (result.raw_trace or [])]
    audit_path = tmp_path / "isaac_p0_audit.jsonl"
    rows = [json.loads(l) for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(
        r.get("trigger_type") == "natural_llm"
        and r.get("decision") == "denied"
        for r in rows
    )


def test_owner_private_tool_call_isaac_p0_health_with_agent_endorsement(tmp_path, monkeypatch):
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(p0_mod, "_resolve_isaac_audit_dir", lambda: tmp_path)
    cfg = _cfg(tmp_path)

    def endorsed_handler(msg, **kwargs):
        return p0_mod.handle_isaac_agent_bus_p0_message(
            msg, isaac_agent=_mock_agent("health"), **kwargs
        )

    with patch.object(exec_mod, "handle_isaac_agent_bus_p0_message", endorsed_handler):
        result = _run(exec_mod.execute_owner_toolbox_tool_async(
            "isaac_p0",
            {"command_text": "health", "_context_channel": "private", "_context_user_id": OWNER_UID},
            cfg,
            model_router=MagicMock(),
            context_channel="private",
        ))
    assert result.handled is True
    assert result.allowed is True
    rows = [json.loads(l) for l in (tmp_path / "isaac_p0_audit.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(
        r.get("trigger_type") == "natural_llm"
        and r.get("decision") == "handled"
        and r.get("task_type") == "health_report"
        and r.get("agent_chosen_tool") == "health"
        for r in rows
    )


# ---------- 3) slash fallback 三个入口 ----------

@pytest.mark.parametrize("head", ["i叔", "I叔", "艾萨克"])
def test_slash_fallback_three_entries(head, tmp_path, monkeypatch):
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(p0_mod, "_resolve_isaac_audit_dir", lambda: tmp_path)
    text = f"/{head} health"
    msg = SimpleNamespace(
        text=text, raw_content=text,
        channel="private", is_owner=True,
        uid=OWNER_UID, user_id=OWNER_UID, group_id="",
    )
    result = _run(handle_owner_toolbox_light_message(msg, config=_cfg(tmp_path)))
    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "pass"
    assert "not_isaac_command" not in str(result.reply or "")
    assert (result.data or {}).get("task_type") == "health_report"
    # slash fallback 不经 LLM 路径，会写 audit slash_fallback
    audit_path = tmp_path / "isaac_p0_audit.jsonl"
    rows = [json.loads(l) for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(
        r.get("trigger_type") == "slash_fallback"
        and r.get("decision") == "handled"
        and r.get("task_type") == "health_report"
        for r in rows
    ), f"no handled slash_fallback audit for /{head}"




@pytest.mark.parametrize("text, expected_type", [
    ("/i叔 audit", "audit_report"),
    ("/i叔 status", "status_report"),
    ("/艾萨克 audit", "audit_report"),
])
def test_slash_route_preserves_head_for_audit_status(text, expected_type, tmp_path, monkeypatch):
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(p0_mod, "_resolve_isaac_audit_dir", lambda: tmp_path)
    msg = SimpleNamespace(
        text=text, raw_content=text,
        channel="private", is_owner=True,
        uid=OWNER_UID, user_id=OWNER_UID, group_id="",
    )
    result = _run(handle_owner_toolbox_light_message(msg, config=_cfg(tmp_path)))
    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "pass"
    assert (result.data or {}).get("task_type") == expected_type
    assert "Isaac P0 未返回内容" not in str(result.reply or "")
    rows = [json.loads(l) for l in (tmp_path / "isaac_p0_audit.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(
        r.get("trigger_type") == "slash_fallback"
        and r.get("decision") == "handled"
        and r.get("task_type") == expected_type
        for r in rows
    )


# ---------- 4) 非 owner / 群聊不执行 ----------

def test_non_owner_not_executed(tmp_path, monkeypatch):
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(p0_mod, "_resolve_isaac_audit_dir", lambda: tmp_path)
    cfg = _cfg(tmp_path)
    router = _router(cfg, [
        {"content": "", "tool_calls": [{"id": "c1", "name": "isaac_p0", "arguments": {"command_text": "workspace report"}}]},
    ])
    # 群聊 + 非 owner
    result = _run(handle_owner_toolbox_light_llm_message(
        _msg("艾萨克 帮看 workspace", uid="999", channel="group"),
        cfg, model_router=router, project_root=tmp_path,
    ))
    assert "isaac_p0" not in [item.get("tool_name") for item in (result.raw_trace or [])]


# ---------- 5) 输出/审计不含敏感 marker ----------

def test_no_sensitive_markers(tmp_path, monkeypatch):
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(p0_mod, "_resolve_isaac_audit_dir", lambda: tmp_path)
    cfg = _cfg(tmp_path)
    router = _router(cfg, [
        {"content": "", "tool_calls": [{"id": "c1", "name": "isaac_p0", "arguments": {"command_text": "health"}}]},
        "ok",
    ])
    result = _run(handle_owner_toolbox_light_llm_message(_msg("I叔 health"), cfg, model_router=router, project_root=tmp_path))
    blob = json.dumps({
        "reply": getattr(result, "reply", ""),
        "output": getattr(result, "output", ""),
        "data": getattr(result, "data", {}),
    }, ensure_ascii=False, default=str).lower()
    for m in SENSITIVE_MARKERS:
        assert m not in blob, f"sensitive marker '{m}' leaked in output"
    audit_path = tmp_path / "isaac_p0_audit.jsonl"
    if audit_path.exists():
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            for m in SENSITIVE_MARKERS:
                assert m not in line.lower(), f"sensitive marker '{m}' in audit"
