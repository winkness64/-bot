from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import json
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"
SPEC = importlib.util.spec_from_file_location("isaac_agent_bus_p0_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
isaac_agent_bus_p0 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = isaac_agent_bus_p0
SPEC.loader.exec_module(isaac_agent_bus_p0)
handle_isaac_agent_bus_p0_message = isaac_agent_bus_p0.handle_isaac_agent_bus_p0_message


@dataclass
class DummyMessage:
    text: str
    channel: str = "private"
    is_owner: bool = True
    raw_content: str = ""
    uid: str = "335059272"
    group_id: str = ""
    msg_id: str = "dummy-msg"
    nick: str = "阿漂"
    is_at_bot: bool = False
    owner_command: bool = False
    explicit_command: bool = False
    at_user_ids: list[str] = field(default_factory=list)


def _dump(*values: object) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def test_i_line_p0_owner_private_health_roundtrip_passes() -> None:
    msg = DummyMessage(text="/i叔 health")

    result = handle_isaac_agent_bus_p0_message(msg)

    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "pass"
    assert result.task_type == "health_report"
    assert result.request_schema is not None and result.request_schema["valid"] is True
    assert result.result_schema is not None and result.result_schema["valid"] is True
    assert result.worker_result is not None
    assert result.worker_result["executor_enabled"] is False
    assert result.worker_result["host_action_executed"] is False
    assert result.worker_result["workspace_only"] is True
    assert result.worker_result["read_only"] is True
    assert "TaskRequest -> Isaac worker -> TaskResult" in result.reply
    assert "executor_enabled=false" in result.reply
    assert "host_action_executed=false" in result.reply

    request_env = result.task_request["envelope"]  # type: ignore[index]
    result_env = result.task_result["envelope"]  # type: ignore[index]
    assert request_env["message_type"] == "task_request"
    assert request_env["source_agent"] == "yangyang_owner_private"
    assert request_env["target_agent"] == "isaac_worker_p0"
    assert request_env["actor_context"]["owner_verified"] is True
    assert request_env["session_scope"]["visibility"] == "owner_private"
    assert result_env["message_type"] == "task_result"
    assert result_env["source_agent"] == "isaac_worker_p0"
    assert result_env["target_agent"] == "yangyang_owner_private"
    assert result_env["parent_message_id"] == request_env["message_id"]

    serialized = _dump(result.task_request, result.task_result)
    forbidden = [
        "/opt",
        ".env",
        "runtime_config",
        "long_term/memories.jsonl",
        "project_notes",
        "335059272",
        "/i叔 health",
    ]
    for marker in forbidden:
        assert marker not in serialized


def test_i_line_p0_non_isaac_command_is_ignored() -> None:
    result = handle_isaac_agent_bus_p0_message(DummyMessage(text="普通闲聊"))

    assert result.handled is False
    assert result.allowed is False
    assert result.reason == "not_isaac_command"
    assert result.reply == ""


def test_i_line_p0_non_owner_private_is_blocked() -> None:
    result = handle_isaac_agent_bus_p0_message(
        DummyMessage(text="/i叔 health", is_owner=False, uid="10001", nick="路人")
    )

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "owner_only"
    assert "reason=owner_only" in result.reply
    assert result.task_request is None


def test_i_line_p0_group_message_is_blocked_even_if_owner() -> None:
    result = handle_isaac_agent_bus_p0_message(
        DummyMessage(text="/i叔 health", channel="group", is_owner=True, group_id="137918147")
    )

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "private_only"
    assert "reason=private_only" in result.reply
    assert result.task_request is None


def test_i_line_p0_high_risk_command_is_blocked_before_bus() -> None:
    result = handle_isaac_agent_bus_p0_message(DummyMessage(text="/i叔 帮我重启 nonebot 服务"))

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "high_risk_blocked"
    assert "reason=high_risk_blocked" in result.reply
    assert result.task_request is None
    assert result.task_result is None


def test_i_line_p0_workspace_and_plan_tasks_pass_without_executor() -> None:
    cases = [
        ("/i叔 workspace report", "workspace_report"),
        ("/i叔 做个 dry_run plan", "dry_run_plan"),
    ]
    for text, task_type in cases:
        result = handle_isaac_agent_bus_p0_message(DummyMessage(text=text))
        assert result.handled is True
        assert result.allowed is True
        assert result.task_type == task_type
        assert result.worker_result is not None
        assert result.worker_result["executor_enabled"] is False
        assert result.worker_result["host_probe_enabled"] is False
        assert result.worker_result["service_control_enabled"] is False
        assert result.worker_result["production_memory_accessed"] is False


def test_i_line_p0_unknown_low_risk_task_is_blocked() -> None:
    result = handle_isaac_agent_bus_p0_message(DummyMessage(text="/i叔 给我唱首歌"))

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "clarification_required"
    assert "I叔 P1 preview" in result.reply or "I叔 P0 需要二次确认" in result.reply
    assert "clarification_required" in result.reply
    assert result.task_request is None


def test_i_line_p0_agentbus_factory_roundtrip_uses_agent_v03_path(monkeypatch) -> None:
    class MockAgent:
        def __init__(self):
            self.calls = []

        def think(self, *, user_intent: str, request_id: str = ""):
            self.calls.append({"user_intent": user_intent, "request_id": request_id})
            return type("Decision", (), {
                "chosen_tool": "agentbus_factory",
                "blocked_reason": "",
                "reason": "查 AgentBus 工厂",
                "tool_existed": True,
                "model_tier": "gpt_5_5",
                "tool_executed": True,
                "tool_output": {
                    "schema_version": "isaac.agentbus_factory_report.v1",
                    "read_only": True,
                    "latest_run": {"name": "e2e-run", "validation": "PASS"},
                },
                "tool_latency_ms": 12,
                "tool_blocked_reason": "",
            })()

    mock_agent = MockAgent()
    monkeypatch.setattr(isaac_agent_bus_p0, "_build_isaac_agent_for_bus", lambda router: mock_agent)

    result = handle_isaac_agent_bus_p0_message(DummyMessage(text="/i叔 agentbus factory"), model_router=object())

    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "pass"
    assert result.task_type == "agentbus_factory_report"
    assert result.request_schema is not None and result.request_schema["valid"] is True
    assert result.result_schema is not None and result.result_schema["valid"] is True
    assert result.worker_result is not None
    assert result.worker_result["isaac_worker"] == "isaac_agent_v02_readonly_tool"
    assert result.worker_result["provider_network_used"] is False
    diagnostics = result.worker_result["diagnostics"]
    assert diagnostics["agentbus_factory_check"] == "isaac_agent_v02_readonly_tool"
    assert diagnostics["agent_tool_executed"] is True
    assert diagnostics["agentbus_factory_report"]["latest_run"]["name"] == "e2e-run"
    assert result.agent_audit is not None
    assert result.agent_audit["agent_chosen_tool"] == "agentbus_factory"
    assert result.agent_audit["agent_used_tier"] == "gpt_5_5"
    assert mock_agent.calls and mock_agent.calls[-1]["user_intent"] == "agentbus factory"
    assert "host_action_executed=false" in result.reply
    assert "AgentBus 工厂只读报告" in result.reply
