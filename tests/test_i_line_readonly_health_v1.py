from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
P0_MODULE_PATH = PROJECT_ROOT / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"
HEALTH_MODULE_PATH = PROJECT_ROOT / "src" / "plugins" / "yangyang" / "core" / "isaac_readonly_health.py"

P0_SPEC = importlib.util.spec_from_file_location("isaac_agent_bus_p0_health_v1_under_test", P0_MODULE_PATH)
assert P0_SPEC is not None and P0_SPEC.loader is not None
p0 = importlib.util.module_from_spec(P0_SPEC)
sys.modules[P0_SPEC.name] = p0
P0_SPEC.loader.exec_module(p0)
handle_isaac_agent_bus_p0_message = p0.handle_isaac_agent_bus_p0_message

HEALTH_SPEC = importlib.util.spec_from_file_location("isaac_readonly_health_v1_under_test", HEALTH_MODULE_PATH)
assert HEALTH_SPEC is not None and HEALTH_SPEC.loader is not None
health_mod = importlib.util.module_from_spec(HEALTH_SPEC)
sys.modules[HEALTH_SPEC.name] = health_mod
HEALTH_SPEC.loader.exec_module(health_mod)
build_readonly_health_snapshot = health_mod.build_readonly_health_snapshot

RUNTIME_FILES = [
    PROJECT_ROOT / "src/plugins/yangyang/core/isaac_readonly_health.py",
    PROJECT_ROOT / "src/plugins/yangyang/core/isaac_agent_bus_p0.py",
]
FORBIDDEN_IMPORTS = {"subprocess", "requests", "httpx", "openai", "aiohttp", "urllib", "socket"}
FORBIDDEN_CALLS = {"system", "popen", "spawn", "spawnl", "spawnlp", "spawnv", "spawnvp", "execv", "execve"}


def _owner_private(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="private", is_owner=True, uid="owner_redacted")


def _non_owner_private(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="private", is_owner=False, uid="10001")


def _owner_group(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="group", is_owner=True, group_id="137918147")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_readonly_health_snapshot_schema_and_real_workspace_observations() -> None:
    snapshot = build_readonly_health_snapshot(plugin_loaded_marker=True, handler_available=True)

    assert snapshot["schema_version"].startswith("i_line.readonly_health.v1")
    assert snapshot["read_only"] is True
    assert snapshot["workspace_only"] is True
    assert snapshot["gate_state"] == {
        "owner_private_only": True,
        "group_exposure": False,
        "high_risk_blocked": True,
        "provider_enabled": False,
        "executor_enabled": False,
    }
    assert snapshot["runtime_visible"]["plugin_loaded_marker"] is True
    assert snapshot["runtime_visible"]["i_line_module_importable"] is True
    assert snapshot["runtime_visible"]["handler_available"] is True
    assert "log_source_unavailable" in snapshot["recent_errors"]
    assert snapshot["baseline"]["source_available"] is True
    assert snapshot["baseline"]["conclusion"] == "FULL PASS"
    effects = snapshot["external_effects"]
    assert effects["shell_used"] is False
    assert effects["process_spawn_used"] is False
    assert effects["network_used"] is False
    assert effects["provider_network_used"] is False
    assert effects["executor_used"] is False
    assert effects["host_action_executed"] is False
    assert effects["config_modified"] is False
    assert effects["sensitive_body_read"] is False


def test_readonly_health_missing_log_source_does_not_invent_errors(tmp_path: Path) -> None:
    _write(tmp_path / "dist/current_task_result.md", "I_LINE_MVP_STABLE FULL PASS at 2026-06-07T00:00:00Z")
    snapshot = build_readonly_health_snapshot(project_root=tmp_path)

    assert snapshot["recent_errors"]["status"] in {"log_source_unavailable", "no_error_markers_seen_in_safe_sources"}
    assert snapshot["recent_errors"]["error_marker_count"] == 0
    assert snapshot["recent_errors"]["traceback_marker_count"] == 0
    assert snapshot["baseline"]["source_available"] is True


def test_readonly_health_counts_only_safe_project_reports(tmp_path: Path) -> None:
    _write(tmp_path / "dist/current_task_result.md", "I_LINE_MVP_STABLE FULL PASS at 2026-06-07T01:02:03Z")
    _write(tmp_path / "dist/report.md", "Traceback: boom\n1 failed, 2 passed\nERROR x\n")
    snapshot = build_readonly_health_snapshot(project_root=tmp_path)

    assert snapshot["recent_errors"]["status"] == "error_markers_found"
    assert snapshot["recent_errors"]["sampled_source_count"] >= 1
    assert snapshot["recent_errors"]["error_marker_count"] >= 1
    assert snapshot["recent_errors"]["traceback_marker_count"] >= 1
    assert snapshot["recent_errors"]["failed_test_marker_count"] >= 1


def test_readonly_health_protected_sensitive_body_is_not_output(tmp_path: Path) -> None:
    _write(
        tmp_path / "dist/i_line_mvp_stable_20260607.protected_sha_verify.json",
        json.dumps(
            {
                "all_protected_unchanged_vs_manifest_snapshot": True,
                "benign_guard_marker_hits": ["runtime_config"],
            },
            ensure_ascii=False,
        ),
    )
    _write(
        tmp_path / "dist/i_line_mvp_stable_20260607.safety_scan.json",
        json.dumps({"protected_data_entries": ["redacted-a", "redacted-b"]}, ensure_ascii=False),
    )
    snapshot = build_readonly_health_snapshot(project_root=tmp_path)
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)

    assert snapshot["data_integrity"]["sha_match"] is True
    assert snapshot["data_integrity"]["unchanged"] is True
    assert snapshot["data_integrity"]["sensitive_body_read"] is False
    assert snapshot["data_integrity"]["sensitive_body_output"] is False
    assert "redacted-a" not in serialized
    assert "redacted-b" not in serialized
    assert "BEGIN PRIVATE KEY" not in serialized
    assert "Bearer " not in serialized


def test_runtime_health_code_has_no_shell_network_or_host_control_imports_or_calls() -> None:
    for path in RUNTIME_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in FORBIDDEN_IMPORTS
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module.split(".")[0] not in FORBIDDEN_IMPORTS
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    assert func.attr not in FORBIDDEN_CALLS
                    if isinstance(func.value, ast.Name) and func.value.id == "os":
                        assert func.attr not in {"system", "popen"}
                elif isinstance(func, ast.Name):
                    assert func.id not in FORBIDDEN_CALLS


def test_p0_owner_explicit_health_returns_snapshot_fields_and_valid_bus() -> None:
    result = handle_isaac_agent_bus_p0_message(_owner_private("/i叔 health"))

    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "pass"
    assert result.task_type == "health_report"
    assert result.request_schema is not None and result.request_schema["valid"] is True
    assert result.result_schema is not None and result.result_schema["valid"] is True
    assert result.worker_result is not None
    snapshot = result.worker_result["readonly_health_snapshot"]
    assert snapshot["gate_state"]["owner_private_only"] is True
    assert snapshot["gate_state"]["group_exposure"] is False
    assert snapshot["gate_state"]["high_risk_blocked"] is True
    assert snapshot["gate_state"]["provider_enabled"] is False
    assert snapshot["gate_state"]["executor_enabled"] is False
    assert "recent_errors" in snapshot
    assert "baseline" in snapshot
    assert "data_integrity" in snapshot
    assert "readonly_health_snapshot=" in result.reply
    assert "provider_enabled=false" in result.reply
    assert "executor_enabled=false" in result.reply
    assert "sensitive_body_output=false" in result.reply


def test_owner_private_natural_language_health_delegate_not_regex_fallback() -> None:
    result = handle_isaac_agent_bus_p0_message(_owner_private("麻烦 I叔 看看系统状态有没有报错"))

    assert result.handled is False
    assert result.allowed is False
    assert result.reason == "not_isaac_command"
    assert result.task_request is None
    assert result.task_result is None
    assert result.worker_result is None


def test_group_non_owner_and_high_risk_do_not_call_health_builder() -> None:
    with patch.object(p0, "build_readonly_health_snapshot", side_effect=AssertionError("health builder must not run")):
        group = handle_isaac_agent_bus_p0_message(_owner_group("/i叔 health"))
        non_owner = handle_isaac_agent_bus_p0_message(_non_owner_private("/i叔 health"))
        high_risk = handle_isaac_agent_bus_p0_message(_owner_private("/i叔 health 然后 systemctl restart 服务"))

    assert group.handled is True and group.allowed is False and group.reason == "private_only"
    assert non_owner.handled is True and non_owner.allowed is False and non_owner.reason == "owner_only"
    assert high_risk.handled is True and high_risk.allowed is False and high_risk.reason == "high_risk_blocked"
    assert group.task_request is None and non_owner.task_request is None and high_risk.task_request is None


def test_health_snapshot_bus_payload_remains_redacted_and_no_sensitive_paths() -> None:
    result = handle_isaac_agent_bus_p0_message(_owner_private("/i叔 health"))
    serialized = json.dumps([result.task_request, result.task_result], ensure_ascii=False, sort_keys=True)

    forbidden = [
        "/opt",
        ".env",
        "runtime_config",
        "long_term/memories.jsonl",
        "project_notes",
        "335059272",
        "I叔 health",
        "BEGIN PRIVATE KEY",
        "Bearer ",
    ]
    for marker in forbidden:
        assert marker not in serialized
