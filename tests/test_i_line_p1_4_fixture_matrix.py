from __future__ import annotations

from dataclasses import asdict, is_dataclass
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from typing import Any, Callable

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "i_line_p1_4_natural_delegation_matrix.jsonl"
INTENT_PATH = ROOT / "src" / "plugins" / "yangyang" / "core" / "isaac_intent_p1.py"
P0_PATH = ROOT / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"


def _load_module(module_name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


intent_mod = _load_module("isaac_intent_p1_p1_4_fixture_matrix_under_test", INTENT_PATH)
p0_mod = _load_module("isaac_agent_bus_p0_p1_4_fixture_matrix_under_test", P0_PATH)

parse_intent_with_provider_dry_run = intent_mod.parse_intent_with_provider_dry_run
handle = p0_mod.handle_isaac_agent_bus_p0_message


FORBIDDEN_LEAK_PATTERNS = (
    r"runtime_config",
    r"long_term",
    r"(?<!agent_bus)\.env",
)


def _load_cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row.setdefault("_line_no", line_no)
            rows.append(row)
    assert rows, f"empty fixture: {FIXTURE_PATH}"
    assert len({row["id"] for row in rows}) == len(rows), "fixture ids must be unique"
    return rows


CASES = _load_cases()


def _message(row: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        text=row["text"],
        raw_content=row["text"],
        channel=row.get("channel", "private"),
        is_owner=bool(row.get("is_owner", False)),
        group_id=row.get("group_id"),
    )


def _provider_for(row: dict[str, Any], calls: list[str]) -> Callable[[str], dict[str, Any]] | None:
    mode = row.get("provider_mode", "none")
    if mode == "none":
        return None
    if mode == "must_not_call":
        def provider(command_text: str) -> dict[str, Any]:
            calls.append(command_text)
            return {
                "intent": "health_report",
                "confidence": 0.99,
                "risk_level": "low",
                "needs_confirmation": False,
                "reason": "sentinel provider should not be called",
                "source": "forbidden_sentinel_provider",
            }

        return provider
    raise AssertionError(f"unknown provider_mode={mode!r} in {row['id']}")


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value


def _serialized(value: Any) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, default=str)


def _assert_no_boundary_leak(serialized: str, raw_text: str) -> None:
    assert raw_text not in serialized
    lowered = serialized.lower()
    for pattern in FORBIDDEN_LEAK_PATTERNS:
        assert re.search(pattern, lowered) is None
    assert "provider_network_used=true" not in lowered
    assert "executor_enabled=true" not in lowered
    assert "host_action_executed=true" not in lowered


def _assert_preview_boundary(preview: dict[str, Any], expected_task_type: str | None) -> None:
    assert preview["no_real_dispatch"] is True
    assert preview["agent_bus_used"] is False
    assert preview["task_request_dispatched"] is False
    assert preview["executor_enabled"] is False
    assert preview["provider_network_used"] is False
    if expected_task_type is not None:
        assert preview["would_dispatch_task_type"] == expected_task_type
        assert preview["candidate"]["intent"] == expected_task_type
        assert preview["candidate"]["source"] == "mock_llm_rules"


@pytest.mark.parametrize("case", CASES, ids=[row["id"] for row in CASES])
def test_p1_4_fixture_matrix_handler_contracts(case: dict[str, Any]) -> None:
    calls: list[str] = []
    result = handle(_message(case), intent_provider=_provider_for(case, calls))
    expect = case["expect"]

    if case.get("provider_mode") == "must_not_call":
        assert calls == []

    assert result.handled is expect["handled"]
    assert result.allowed is expect["allowed"]
    assert result.reason == expect["reason"]
    assert result.task_type == expect["task_type"]

    for needle in expect["reply_contains"]:
        assert needle in result.reply

    if expect["intent_preview"]:
        assert result.intent_preview is not None
        _assert_preview_boundary(result.intent_preview, expect["task_type"])
    else:
        assert result.intent_preview is None
        assert "I叔 P1 preview" not in result.reply

    if expect["p0_task_objects"]:
        assert result.task_request is not None
        assert result.task_result is not None
        assert result.worker_result is not None
        assert result.worker_result["executor_enabled"] is False
        assert result.worker_result["host_action_executed"] is False
        assert result.worker_result["service_control_enabled"] is False
        assert result.worker_result["provider_network_used"] is False
        assert result.worker_result["production_memory_accessed"] is False
    else:
        assert result.task_request is None
        assert result.task_result is None
        assert result.worker_result is None

    _assert_no_boundary_leak(_serialized(result), case["text"])


@pytest.mark.parametrize("case", CASES, ids=[row["id"] for row in CASES])
def test_p1_4_fixture_matrix_parser_contracts(case: dict[str, Any]) -> None:
    expect = case["expect"]
    if expect["parser_reason"] is None:
        pytest.skip("this row validates handler pre-gates such as group/owner/P0 priority")

    calls: list[str] = []
    decision = parse_intent_with_provider_dry_run(case["text"], provider=_provider_for(case, calls))

    if case.get("provider_mode") == "must_not_call":
        assert calls == []

    assert decision.handled is expect["handled"]
    assert decision.allowed is expect["allowed"]
    assert decision.reason == expect["parser_reason"]

    if expect["task_type"] is None:
        assert decision.would_dispatch_task_type is None
    else:
        assert decision.would_dispatch_task_type == expect["task_type"]
        assert decision.candidate is not None
        assert decision.candidate.intent == expect["task_type"]
        assert decision.candidate.source == "mock_llm_rules"

    assert "task_request" not in _serialized(decision).lower()
    _assert_no_boundary_leak(_serialized(decision), case["text"])


def test_p1_4_fixture_contains_required_exact_owner_private_utterances() -> None:
    required = {
        "你帮我让I叔看看系统状态",
        "麻烦艾萨克看下有没有异常",
        "叫I叔汇报今天维护进度",
        "让i叔给个只读计划",
        "I叔你觉得这个怎么处理",
        "你让I叔重启服务",
    }
    covered = {row["text"] for row in CASES}
    assert required <= covered


def test_p1_4_fixture_covers_required_negative_boundaries() -> None:
    by_id = {row["id"]: row for row in CASES}
    assert by_id["english_isaac_health_not_triggered"]["expect"]["reason"] == "not_isaac_command"
    assert by_id["group_system_status_private_only_no_preview"]["expect"]["reason"] == "private_only"
    assert by_id["owner_private_restart_service_high_risk_blocked"]["expect"]["reason"] == "high_risk_blocked"
    assert by_id["owner_private_ambiguous_opinion_clarification"]["expect"]["reason"] == "clarification_required"
    assert by_id["p0_explicit_health_priority_over_p1"]["expect"]["reason"] == "pass"
