#!/usr/bin/env python3
"""Isaac Agent v0.1 unit tests.

跑法：在项目根运行 python3 -m pytest tests/test_isaac_agent_v0.py -v
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

# 让测试能找到 isaac_agent 包
AGENT_PATH = Path(__file__).resolve().parents[1] / "src/plugins/yangyang/core/isaac_agent"
sys.path.insert(0, str(AGENT_PATH))

from agent_v0 import (  # noqa: E402
    READONLY_TOOLS,
    FORBIDDEN_TOOL_PATTERNS,
    IsaacAgent,
    IsaacDecision,
    IsaacMemory,
    V02_EXECUTABLE_TOOLS,
    _sha256_text,
)


# ---- helpers ----

class FakeRouter:
    """假 model_router，模拟 V4 Pro 返回。"""

    def __init__(self, response_text: str = ""):
        self.response_text = response_text
        self.calls = []

    def call_via_tier(self, tier, messages, target_agent=""):
        self.calls.append({"tier": tier, "target_agent": target_agent, "messages": messages})
        return {"content": self.response_text}


def _make_agent(router=None, tmpdir=None):
    tmp = Path(tmpdir) if tmpdir else Path(tempfile.mkdtemp(prefix="isaac_test_"))
    prompt = AGENT_PATH / "prompt_v0.md"
    memory = tmp / "memory.jsonl"
    return IsaacAgent(model_router=router or FakeRouter(), prompt_path=prompt, memory_path=memory), tmp


# ---- tests ----

def test_prompt_file_exists():
    assert (AGENT_PATH / "prompt_v0.md").exists(), "prompt_v0.md 必须在 isaac_agent 目录里"


def test_prompt_contains_core_directives():
    txt = (AGENT_PATH / "prompt_v0.md").read_text(encoding="utf-8")
    must_have = [
        "Isaac Clarke",
        "readonly",
        "Agent Bus",
        "BLOCKED",
        "health",
        "workspace",
        "audit",
        "status",
        "dry_run_plan",
        "agentbus_factory",
    ]
    for kw in must_have:
        assert kw in txt, f"prompt 缺少关键词: {kw}"


def test_readonly_tools_count_and_names():
    names = {t["name"] for t in READONLY_TOOLS}
    assert names == {"health", "workspace", "audit", "status", "dry_run_plan", "agentbus_factory"}
    for t in READONLY_TOOLS:
        assert t["risk"] == "low"


def test_forbidden_patterns_blocked():
    agent, tmp = _make_agent()
    for pattern in ("write", "deploy", "restart", "shell", "memory_write", "config_write"):
        assert agent._is_forbidden(pattern), f"应被拦: {pattern}"
    shutil.rmtree(tmp, ignore_errors=True)


def test_llm_picks_health_for_health_intent():
    router = FakeRouter(response_text='{"chosen_tool": "health", "reason": "查系统状态"}')
    agent, tmp = _make_agent(router)
    d = agent.think("看看系统状态", request_id="t1")
    assert d.chosen_tool == "health"
    assert d.tool_existed is True
    assert d.blocked_reason == ""
    assert d.reason == "查系统状态"
    assert d.model_tier == "v4_pro"
    assert d.prompt_sha != ""
    assert d.tool_registry_sha != ""
    shutil.rmtree(tmp, ignore_errors=True)


def test_llm_picks_dry_run_plan_for_classify():
    router = FakeRouter(response_text='{"chosen_tool": "dry_run_plan", "reason": "分类提议"}')
    agent, tmp = _make_agent(router)
    d = agent.think("把这条命令分类一下")
    assert d.chosen_tool == "dry_run_plan"
    assert d.blocked_reason == ""
    shutil.rmtree(tmp, ignore_errors=True)


def test_llm_picks_agentbus_factory_for_worker_factory():
    router = FakeRouter(response_text='{"chosen_tool": "agentbus_factory", "reason": "查最近工厂验尸报告"}')
    agent, tmp = _make_agent(router)
    d = agent.think("看看黑奴工厂最近一次验尸报告")
    assert d.chosen_tool == "agentbus_factory"
    assert d.blocked_reason == ""
    shutil.rmtree(tmp, ignore_errors=True)


def test_forbidden_tool_gets_blocked():
    """LLM 想调 write，必须被拦下。"""
    router = FakeRouter(response_text='{"chosen_tool": "write_file", "reason": "写文件"}')
    agent, tmp = _make_agent(router)
    d = agent.think("帮我写个文件")
    assert d.chosen_tool == ""
    assert "forbidden" in d.blocked_reason
    shutil.rmtree(tmp, ignore_errors=True)


def test_unknown_tool_gets_blocked():
    """LLM 想调不在 registry 的工具，必须被拦下。"""
    router = FakeRouter(response_text='{"chosen_tool": "restart_service", "reason": "重启"}')
    agent, tmp = _make_agent(router)
    d = agent.think("重启服务")
    assert d.chosen_tool == ""
    # restart_service 含 restart pattern → forbidden
    assert "forbidden" in d.blocked_reason or "not_in_registry" in d.blocked_reason
    shutil.rmtree(tmp, ignore_errors=True)


def test_llm_returns_null_passes_through():
    router = FakeRouter(response_text='{"chosen_tool": null, "reason": "没有合适的只读工具"}')
    agent, tmp = _make_agent(router)
    d = agent.think("帮我说甜话给珂老师听")
    assert d.chosen_tool == ""
    assert d.blocked_reason == ""  # null 是合法选择，不算 blocked
    assert "甜话" in d.reason or "没有" in d.reason
    shutil.rmtree(tmp, ignore_errors=True)


def test_markdown_wrapped_json_parsed():
    router = FakeRouter(response_text='```json\n{"chosen_tool": "audit", "reason": "查审计"}\n```')
    agent, tmp = _make_agent(router)
    d = agent.think("看看审计")
    assert d.chosen_tool == "audit"
    shutil.rmtree(tmp, ignore_errors=True)


def test_llm_error_does_not_crash():
    class BadRouter:
        def call_via_tier(self, tier, messages, target_agent=""):
            raise RuntimeError("V4 爆了")

    agent, tmp = _make_agent(BadRouter())
    d = agent.think("看看")
    assert d.chosen_tool == ""
    assert "llm_error" in d.blocked_reason
    assert "V4 爆了" in d.blocked_reason
    shutil.rmtree(tmp, ignore_errors=True)


def test_memory_persists_decisions():
    router = FakeRouter(response_text='{"chosen_tool": "health", "reason": "ok"}')
    agent, tmp = _make_agent(router)
    for i in range(3):
        agent.think(f"第 {i} 次")
    assert agent.memory.count() == 3
    tail = agent.memory.tail(10)
    assert len(tail) == 3
    assert tail[-1]["chosen_tool"] == "health"
    shutil.rmtree(tmp, ignore_errors=True)


def test_stats_returns_metadata():
    router = FakeRouter(response_text='{"chosen_tool": "workspace", "reason": "项目概览"}')
    agent, tmp = _make_agent(router)
    agent.think("看看项目")
    s = agent.stats()
    assert s["tool_count"] == 6
    assert s["memory_count"] == 1
    assert s["prompt_sha"] != ""
    assert s["tool_registry_sha"] != ""
    shutil.rmtree(tmp, ignore_errors=True)


def test_no_sensitive_markers_in_prompt():
    """prompt 不能含任何敏感 marker 明文。"""
    txt = (AGENT_PATH / "prompt_v0.md").read_text(encoding="utf-8")
    bad = ("api_key=", "token=", "secret=", "password=", "sk-", "private_key=")
    for marker in bad:
        assert marker not in txt.lower(), f"prompt 漏敏感 marker: {marker}"


def test_no_wriite_in_registry():
    """工具 registry 只能有只读工具，名字里不能含写/部署/重启。"""
    for t in READONLY_TOOLS:
        n = t["name"].lower()
        for p in FORBIDDEN_TOOL_PATTERNS:
            assert p not in n, f"工具 {n} 不该有 pattern {p}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))


# ---- v0.2 readonly execution slice ----

def _json_blob(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def test_v02_executable_tools_constant_is_locked():
    assert V02_EXECUTABLE_TOOLS == frozenset({"agentbus_factory"})


def test_agentbus_factory_tool_actually_runs_when_llm_picks_it():
    router = FakeRouter(response_text='{"chosen_tool": "agentbus_factory", "reason": "查最近工厂验尸报告"}')
    agent, tmp = _make_agent(router)
    d = agent.think("看看黑奴工厂最近一次验尸报告", request_id="v02-factory")
    assert d.chosen_tool == "agentbus_factory"
    assert d.blocked_reason == ""
    assert d.tool_executed is True
    assert isinstance(d.tool_output, dict)
    assert d.tool_latency_ms >= 0
    assert d.tool_output.get("status") in {"PASS", "PARTIAL", "WARN", "UNKNOWN", "NO_RUNS", "ERROR", "truncated", "ok"}
    shutil.rmtree(tmp, ignore_errors=True)


def test_agentbus_factory_output_redacts_absolute_paths():
    router = FakeRouter(response_text='{"chosen_tool": "agentbus_factory", "reason": "查最近工厂验尸报告"}')
    agent, tmp = _make_agent(router)
    d = agent.think("看看 AgentBus 工厂", request_id="v02-redact")
    blob = _json_blob(d.tool_output)
    forbidden = ["/root/data", "/mnt", "/opt/yangyang_nonebot", ".env", "runtime_config", "long_term/memories.jsonl", "base_url", "api_key", "token", "secret", "password"]
    for marker in forbidden:
        assert marker not in blob, marker
    shutil.rmtree(tmp, ignore_errors=True)


def test_health_tool_not_executed_in_v02_but_still_resolves():
    router = FakeRouter(response_text='{"chosen_tool": "health", "reason": "查系统状态"}')
    agent, tmp = _make_agent(router)
    d = agent.think("看看系统状态", request_id="v02-health")
    assert d.chosen_tool == "health"
    assert d.blocked_reason == ""
    assert d.tool_existed is True
    assert d.tool_executed is False
    assert d.tool_output == {"status": "not_executable_in_v02", "tool": "health"}
    assert d.tool_blocked_reason == "not_executable_in_v02"
    tail = agent.memory.tail(1)[0]
    assert tail["chosen_tool"] == "health"
    assert tail["tool_executed"] is False
    assert tail["tool_output"]["status"] == "not_executable_in_v02"
    shutil.rmtree(tmp, ignore_errors=True)


def test_forbidden_tool_still_blocked_before_execution_v02():
    router = FakeRouter(response_text='{"chosen_tool": "write_file", "reason": "写文件"}')
    agent, tmp = _make_agent(router)
    d = agent.think("帮我写文件", request_id="v02-forbidden")
    assert d.chosen_tool == ""
    assert d.tool_executed is False
    assert d.tool_output == {}
    assert "forbidden_tool_requested: write_file" in d.blocked_reason
    assert d.tool_blocked_reason == ""
    shutil.rmtree(tmp, ignore_errors=True)


def test_v02_decision_field_round_trip_in_jsonl():
    router = FakeRouter(response_text='{"chosen_tool": "agentbus_factory", "reason": "查最近工厂验尸报告"}')
    agent, tmp = _make_agent(router)
    agent.think("看看工厂", request_id="v02-jsonl")
    row = json.loads((tmp / "memory.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
    for key in ("tool_executed", "tool_output", "tool_latency_ms", "tool_blocked_reason"):
        assert key in row
    assert row["tool_executed"] is True
    assert isinstance(row["tool_output"], dict)
    shutil.rmtree(tmp, ignore_errors=True)


def test_tool_exception_persists_decision_without_crash(monkeypatch):
    router = FakeRouter(response_text='{"chosen_tool": "agentbus_factory", "reason": "查最近工厂验尸报告"}')
    agent, tmp = _make_agent(router)

    def boom(tool_name):
        return True, {"status": "tool_exception", "tool": tool_name}, 1, "RuntimeError: boom"

    monkeypatch.setattr(agent, "_execute_readonly_tool", boom)
    d = agent.think("看看工厂", request_id="v02-exc")
    assert d.tool_executed is True
    assert d.tool_output["status"] == "tool_exception"
    assert "RuntimeError" in d.tool_blocked_reason
    row = agent.memory.tail(1)[0]
    assert row["tool_output"]["status"] == "tool_exception"
    shutil.rmtree(tmp, ignore_errors=True)


def test_execute_readonly_tool_rejects_empty_tool_directly():
    agent, tmp = _make_agent()
    executed, output, latency_ms, reason = agent._execute_readonly_tool("")
    assert executed is False
    assert output == {}
    assert latency_ms == 0
    assert reason == "no_tool_chosen"
    shutil.rmtree(tmp, ignore_errors=True)


def test_execute_readonly_tool_rejects_forbidden_tool_directly():
    agent, tmp = _make_agent()
    executed, output, latency_ms, reason = agent._execute_readonly_tool("write_file")
    assert executed is False
    assert output == {"status": "blocked", "tool": "write_file"}
    assert latency_ms == 0
    assert reason == "forbidden_tool_requested: write_file"
    shutil.rmtree(tmp, ignore_errors=True)


def test_execute_readonly_tool_rejects_unknown_tool_directly():
    agent, tmp = _make_agent()
    executed, output, latency_ms, reason = agent._execute_readonly_tool("factory_unknown")
    assert executed is False
    assert output == {"status": "blocked", "tool": "factory_unknown"}
    assert latency_ms == 0
    assert reason == "tool_not_in_registry: factory_unknown"
    shutil.rmtree(tmp, ignore_errors=True)


def test_execute_readonly_tool_rejects_registered_but_not_v02_executable_directly():
    agent, tmp = _make_agent()
    executed, output, latency_ms, reason = agent._execute_readonly_tool("health")
    assert executed is False
    assert output == {"status": "not_executable_in_v02", "tool": "health"}
    assert latency_ms == 0
    assert reason == "not_executable_in_v02"
    shutil.rmtree(tmp, ignore_errors=True)


def test_redact_tool_output_removes_forbidden_fragments_directly():
    from agent_v0 import _redact_tool_output

    redacted = _redact_tool_output({
        "path": "/opt/yangyang_nonebot/src/plugins/yangyang/.env",
        "nested": ["api_key=abc", "safe"],
        "plain": "hello",
    })
    blob = _json_blob(redacted)
    assert "/opt/yangyang_nonebot" not in blob
    assert ".env" not in blob
    assert "api_key" not in blob
    assert "hello" in blob


def test_compact_tool_output_truncates_large_payload_directly():
    from agent_v0 import _compact_tool_output

    compact = _compact_tool_output({"big": "x" * 5000}, limit=200)
    assert compact["status"] == "truncated"
    assert compact["truncated"] is True
    assert compact["chars"] > 200
    assert len(compact["preview"]) == 200

class FakeRuntimeConfig:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, path, default=None):
        return self.values.get(path, default)


class FakeRouterWithConfig(FakeRouter):
    def __init__(self, response_text: str, values):
        super().__init__(response_text=response_text)
        self.runtime_cfg = FakeRuntimeConfig(values)


def test_isaac_model_profile_can_be_overridden_from_runtime_config():
    router = FakeRouterWithConfig(
        response_text='{"chosen_tool": "health", "reason": "查系统状态"}',
        values={"isaac.model_profile": "gpt_5_5"},
    )
    agent, tmp = _make_agent(router)
    d = agent.think("看看系统状态", request_id="isaac-gpt55")
    assert router.calls[-1]["tier"] == "gpt_5_5"
    assert d.model_tier == "gpt_5_5"
    shutil.rmtree(tmp, ignore_errors=True)


def test_isaac_model_profile_override_does_not_change_global_switcher_defaults():
    from agent_v0 import _resolve_isaac_model_tier

    router = FakeRouterWithConfig(
        response_text='{"chosen_tool": "health", "reason": "查系统状态"}',
        values={
            "isaac.model_profile": "gpt_5_5",
            "model_profile_switcher.active_profile_private": "v4_flash",
            "model_profile_switcher.active_profile_group": "v4_flash",
        },
    )
    assert _resolve_isaac_model_tier(router) == "gpt_5_5"
    assert router.runtime_cfg.get("model_profile_switcher.active_profile_private") == "v4_flash"
    assert router.runtime_cfg.get("model_profile_switcher.active_profile_group") == "v4_flash"

