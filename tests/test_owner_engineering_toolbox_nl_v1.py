from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "owner_engineering_toolbox.py"
SPEC = importlib.util.spec_from_file_location("owner_engineering_toolbox_nl_v1_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
toolbox_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = toolbox_mod
SPEC.loader.exec_module(toolbox_mod)

handle_nl = toolbox_mod.handle_owner_engineering_toolbox_message_nl_async
parse_plan = toolbox_mod.parse_toolbox_intent_plan

OWNER_UID = "335059272"


def _cfg(**overrides: Any) -> dict[str, Any]:
    data = {
        "owner_uid": OWNER_UID,
        "owner_uids": [OWNER_UID],
        "owner_engineering_toolbox_enabled": True,
        "owner_engineering_toolbox_nl_enabled": True,
        "owner_engineering_toolbox_llm_parser_enabled": True,
        "owner_engineering_toolbox_low_risk_enabled": True,
        "owner_engineering_toolbox_write_enabled": True,
        "owner_engineering_toolbox_shell_enabled": True,
        "owner_engineering_toolbox_python_enabled": True,
        "owner_engineering_toolbox_audit_enabled": True,
        "owner_engineering_toolbox_timeout_seconds": 2,
        "owner_engineering_toolbox_max_output_chars": 2000,
        "owner_engineering_toolbox_max_read_lines": 20,
        "owner_engineering_toolbox_max_read_bytes": 10000,
        "owner_engineering_toolbox_max_grep_results": 10,
        "owner_engineering_toolbox_max_grep_files": 50,
        "owner_engineering_toolbox_max_list_entries": 20,
        "owner_engineering_toolbox_max_pack_files": 50,
    }
    data.update(overrides)
    return data


def _msg(text: str, *, uid: str = OWNER_UID, channel: str = "private", is_owner: bool | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        raw_content=text,
        uid=uid,
        channel=channel,
        is_owner=(uid == OWNER_UID if is_owner is None else is_owner),
        group_id="137918147" if channel == "group" else "",
        msg_id="toolbox-nl-test-msg",
    )


def _provider(plan: dict[str, Any]):
    async def provider(text: str, context: dict[str, Any]) -> dict[str, Any]:
        assert text
        assert context["schema_version"] == toolbox_mod.NL_SCHEMA_VERSION
        return plan

    return provider


def _run(coro):
    return asyncio.run(coro)


def test_nl_llm_parser_is_primary_for_natural_variants(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "demo.md").write_text("hello nl parser\n", encoding="utf-8")
    plan = {"action": "execute", "tool": "read_file", "risk_level": "low", "confidence": 0.93, "args": {"path": "docs/demo.md"}}

    result = _run(handle_nl(_msg("帮我看一下 demo 文档里写了啥"), _cfg(), project_root=tmp_path, intent_provider=_provider(plan)))

    assert result.handled is True
    assert result.allowed is True
    assert result.tool_name == "read_file"
    assert result.intent_plan is not None and result.intent_plan.source == "llm_intent_provider"
    assert "hello nl parser" in result.reply


def test_nl_medium_write_executes_by_default_for_owner_private(tmp_path: Path) -> None:
    plan = {
        "action": "execute",
        "tool": "write_file",
        "risk_level": "medium",
        "confidence": 0.91,
        "args": {"path": "notes/nl.txt", "content": "natural write ok"},
    }

    result = _run(handle_nl(_msg("给我新建一个笔记写上这句话"), _cfg(), project_root=tmp_path, intent_provider=_provider(plan)))

    assert result.handled is True
    assert result.allowed is True
    assert result.execution is not None and result.execution.real_write is True
    assert (tmp_path / "notes" / "nl.txt").read_text(encoding="utf-8") == "natural write ok"


def test_nl_ordinary_chat_does_not_trigger_without_provider(tmp_path: Path) -> None:
    result = _run(handle_nl(_msg("辛苦了，晚上好"), _cfg(), project_root=tmp_path))

    assert result.handled is False
    assert result.intent_plan is not None and result.intent_plan.action == "none"


def test_nl_high_risk_natural_language_does_not_execute(tmp_path: Path) -> None:
    result = _run(handle_nl(_msg("帮我重启 nonebot 服务看下"), _cfg(), project_root=tmp_path))

    assert result.handled is True
    assert result.allowed is False
    assert result.execution is None
    assert result.intent_plan is not None and result.intent_plan.action == "confirm"
    assert "high_risk" in result.reply or "高风险" in result.reply


def test_nl_sensitive_and_production_paths_are_blocked_before_llm(tmp_path: Path) -> None:
    calls: list[str] = []

    async def provider(text: str, context: dict[str, Any]) -> dict[str, Any]:
        calls.append(text)
        return {"action": "execute", "tool": "read_file", "risk_level": "low", "confidence": 0.99, "args": {"path": "/opt/yangyang_nonebot/.env"}}

    result = _run(handle_nl(_msg("帮我读取 /opt/yangyang_nonebot/.env 文件"), _cfg(), project_root=tmp_path, intent_provider=provider))

    assert calls == []
    assert result.handled is True
    assert result.allowed is False
    assert result.execution is None
    assert "受控工作区" in result.reply or "敏感" in result.reply
    assert "production_path_blocked" not in result.reply
    assert "/opt" not in result.reply


def test_nl_group_and_non_owner_are_disabled_even_if_toolish(tmp_path: Path) -> None:
    group = _run(handle_nl(_msg("帮我列一下目录", channel="group", is_owner=True), _cfg(), project_root=tmp_path))
    non_owner = _run(handle_nl(_msg("帮我列一下目录", uid="10086", is_owner=False), _cfg(), project_root=tmp_path))

    assert group.handled is True and group.allowed is False and group.reason == "private_only" and group.reply == ""
    assert non_owner.handled is True and non_owner.allowed is False and non_owner.reason == "owner_only"
    assert "owner 私聊" in non_owner.reply
    assert "owner_private_only" not in non_owner.reply


def test_nl_provider_clarification_plan_is_not_executed(tmp_path: Path) -> None:
    plan = {"action": "clarify", "tool": "grep", "risk_level": "low", "confidence": 0.82, "reason": "missing_query", "reply": "要搜什么关键词？"}

    result = _run(handle_nl(_msg("帮我搜一下项目"), _cfg(), project_root=tmp_path, intent_provider=_provider(plan)))

    assert result.handled is True
    assert result.allowed is False
    assert result.execution is None
    assert "clarification_required" not in result.reply
    assert "reason=" not in result.reply
    assert "confidence=" not in result.reply
    assert "要搜什么关键词" in result.reply


def test_nl_fixed_shell_high_risk_marker_is_confirm_not_execute(tmp_path: Path) -> None:
    result = _run(handle_nl(_msg("工具箱 shell sudo systemctl restart nonebot"), _cfg(), project_root=tmp_path))

    assert result.handled is True
    assert result.allowed is False
    assert result.execution is None
    assert result.gate is not None and result.gate.reason == "high_risk_requires_confirm"
    assert "高风险" in result.reply
    assert "high_risk_requires_confirm" not in result.reply


def test_nl_provider_shell_high_risk_marker_is_confirm_even_if_mislabeled(tmp_path: Path) -> None:
    plan = {"action": "execute", "tool": "shell", "risk_level": "medium", "confidence": 0.95, "args": {"command": "sudo systemctl restart nonebot"}}

    result = _run(handle_nl(_msg("帮我执行维护命令"), _cfg(), project_root=tmp_path, intent_provider=_provider(plan)))

    assert result.handled is True
    assert result.allowed is False
    assert result.execution is None
    assert result.gate is not None and result.gate.reason == "high_risk_requires_confirm"
    assert "高风险" in result.reply
    assert "high_risk_requires_confirm" not in result.reply


def test_nl_model_router_json_plan_is_used(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('x')\n", encoding="utf-8")

    class Router:
        async def call(self, tier, messages, temperature=0.72, session_id=None):
            assert tier == "v4_flash"
            assert temperature == 0.0
            assert session_id == "owner_toolbox_nl"
            assert "intent parser" in messages[0]["content"]
            return json.dumps({"action": "execute", "tool": "list_dir", "risk_level": "low", "confidence": 0.9, "args": {"path": "src"}}), "stub"

    result = _run(handle_nl(_msg("看下源码目录"), _cfg(), project_root=tmp_path, model_router=Router()))

    assert result.handled is True
    assert result.allowed is True
    assert result.intent_plan is not None and result.intent_plan.source == "llm_model_router:stub"
    assert "a.py" in result.reply


def _assert_no_raw_fields(reply: str) -> None:
    forbidden = ["[owner_toolbox]", "[owner_toolbox_nl]", "tool=", "risk=", "mode=", "owner_private_only=", "real_write=", "real_execute=", "confidence=", "reason="]
    for token in forbidden:
        assert token not in reply


def test_formatter_nl_list_tmp_is_natural_without_raw_fields(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()

    result = _run(handle_nl(_msg("帮我看一下 tmp 目录有什么"), _cfg(), project_root=tmp_path))

    assert result.handled is True
    assert result.allowed is True
    assert result.raw_reply.startswith("[owner_toolbox]")
    assert result.reply == "tmp 目录是空的。"
    assert result.formatted_text == result.reply
    _assert_no_raw_fields(result.reply)

    (tmp_path / "tmp" / "a").write_text("a", encoding="utf-8")
    (tmp_path / "tmp" / "b").mkdir()
    result2 = _run(handle_nl(_msg("帮我看一下 tmp 目录有什么"), _cfg(), project_root=tmp_path))
    assert "tmp 里有：" in result2.reply
    assert "a" in result2.reply and "b" in result2.reply
    _assert_no_raw_fields(result2.reply)


def test_formatter_python_expression_is_natural_without_raw_fields(tmp_path: Path) -> None:
    result = _run(handle_nl(_msg("用 python 算一下 1+1"), _cfg(), project_root=tmp_path))

    assert result.handled is True
    assert result.allowed is True
    assert "2" in result.reply
    assert result.reply == "结果是 2。"
    assert result.raw_reply.startswith("[owner_toolbox]")
    _assert_no_raw_fields(result.reply)


def test_formatter_cold_backup_clarification_hides_raw_fields_and_opt(tmp_path: Path) -> None:
    result = _run(handle_nl(_msg("看下我们冷备份目录里面有什么"), _cfg(), project_root=tmp_path))

    assert result.handled is True
    assert result.allowed is False
    assert result.execution is None
    assert result.reply == "冷备相关不能直接展开路径；请给相对工作区路径，或走受控交接。"
    _assert_no_raw_fields(result.reply)
    assert "/opt" not in result.reply
    assert "missing_controlled_workspace_path" in result.raw_reply


def test_formatter_debug_status_keeps_raw_report(tmp_path: Path) -> None:
    result = _run(handle_nl(_msg("工具箱 debug status"), _cfg(), project_root=tmp_path))

    assert result.handled is True
    assert result.allowed is True
    assert result.reply.startswith("[owner_toolbox]")
    assert "tool=toolbox_status" in result.reply
    assert "risk=" in result.reply
    assert result.formatted_text == result.reply



def test_nl_safe_absolute_workspace_root_outside_project_is_allowed(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    workspace = tmp_path / "owner_engineering_toolbox_workspace"
    project_root.mkdir()
    (workspace / "tmp").mkdir(parents=True)

    result = _run(
        handle_nl(
            _msg("帮我看一下 tmp 目录有什么"),
            _cfg(owner_engineering_toolbox_workspace_root=str(workspace)),
            project_root=project_root,
        )
    )

    assert result.handled is True
    assert result.allowed is True
    assert result.gate is not None and result.gate.workspace_root == str(workspace.resolve())
    assert result.reply == "tmp 目录是空的。"
    _assert_no_raw_fields(result.reply)


def test_nl_status_not_blocked_by_forbidden_workspace_root(tmp_path: Path) -> None:
    result = _run(
        handle_nl(
            _msg("工具箱 status"),
            _cfg(owner_engineering_toolbox_workspace_root="/opt/yangyang_nonebot"),
            project_root=tmp_path,
        )
    )

    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "status_ok"
    assert result.reply == "工具箱正常。"
    assert "[owner_toolbox]" not in result.reply
    assert "tool=" not in result.reply
    assert "workspace_root=" not in result.reply


def test_nl_high_confidence_missing_code_from_model_falls_back_to_python_expression(tmp_path: Path) -> None:
    plan = {"action": "clarify", "tool": "none", "risk_level": "low", "confidence": 0.90, "reason": "ambiguous_tool_request"}

    result = _run(handle_nl(_msg("用 python 算一下 1+1"), _cfg(), project_root=tmp_path, intent_provider=_provider(plan)))

    assert result.handled is True
    assert result.allowed is True
    assert result.tool_name == "python"
    assert result.reply == "结果是 2。"
    _assert_no_raw_fields(result.reply)


def test_nl_debug_raw_config_still_returns_raw_report(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()

    result = _run(handle_nl(_msg("帮我看一下 tmp 目录有什么"), _cfg(owner_engineering_toolbox_raw_report_enabled=True), project_root=tmp_path))

    assert result.handled is True
    assert result.allowed is True
    assert result.reply.startswith("[owner_toolbox]")
    assert "tool=list_dir" in result.reply
    assert "risk=" in result.reply

def test_formatter_audit_keeps_original_fields(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    audit_rel = "logs/audit.jsonl"
    result = _run(handle_nl(_msg("帮我看一下 tmp 目录有什么"), _cfg(owner_engineering_toolbox_audit_path=audit_rel), project_root=tmp_path))

    assert result.handled is True
    assert "tool=" not in result.reply
    audit_path = tmp_path / audit_rel
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records
    assert records[-1]["tool"] == "list_dir"
    assert records[-1]["status"] == "ok"
    assert records[-1]["reason"] == "list_ok"
    assert records[-1]["risk_level"] == "low"
    assert records[-1]["mode"] == "execute"
    assert records[-1]["raw_report_fields"]["tool"] == "list_dir"
    assert records[-1]["raw_report_fields"]["risk"] == "low"
    assert records[-1]["raw_report_fields"]["mode"] == "execute"
    assert records[-1]["raw_report_fields"]["owner_private_only"] is True
