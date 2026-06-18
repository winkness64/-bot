from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "owner_engineering_toolbox.py"
SPEC = importlib.util.spec_from_file_location("owner_engineering_toolbox_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
toolbox_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = toolbox_mod
SPEC.loader.exec_module(toolbox_mod)
evaluate_toolbox_gate = toolbox_mod.evaluate_toolbox_gate
handle_owner_engineering_toolbox_message = toolbox_mod.handle_owner_engineering_toolbox_message
parse_toolbox_command = toolbox_mod.parse_toolbox_command


OWNER_UID = "335059272"


def _cfg(**overrides):
    data = {
        "owner_uid": OWNER_UID,
        "owner_uids": [OWNER_UID],
        "owner_engineering_toolbox_enabled": True,
        "owner_engineering_toolbox_low_risk_enabled": True,
        "owner_engineering_toolbox_max_read_lines": 3,
        "owner_engineering_toolbox_max_read_bytes": 50,
        "owner_engineering_toolbox_max_grep_results": 2,
        "owner_engineering_toolbox_max_grep_files": 50,
        "owner_engineering_toolbox_max_list_entries": 10,
    }
    data.update(overrides)
    return data


def _msg(text: str, *, uid: str = OWNER_UID, channel: str = "private", is_owner: bool | None = None):
    return SimpleNamespace(
        text=text,
        raw_content=text,
        uid=uid,
        channel=channel,
        is_owner=(uid == OWNER_UID if is_owner is None else is_owner),
        group_id="137918147" if channel == "group" else "",
        msg_id="toolbox-test-msg",
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_toolbox_owner_private_status_gate_passes(tmp_path: Path) -> None:
    command = parse_toolbox_command("工具箱 status")
    gate = evaluate_toolbox_gate(command, _msg("工具箱 status"), _cfg(), project_root=tmp_path)

    assert command is not None
    assert command.tool_name == "toolbox_status"
    assert gate.allowed is True
    assert gate.actor == "owner_private"
    assert gate.risk_level == "low"
    assert gate.safe_to_execute is True
    assert gate.workspace_root == str(tmp_path.resolve())

    result = handle_owner_engineering_toolbox_message(_msg("工具箱 status"), _cfg(), project_root=tmp_path)
    assert result.handled is True
    assert result.allowed is True
    assert result.gate is not None and result.gate.actor == "owner_private"
    assert result.execution is not None and result.execution.real_execute is False
    # M3 redo: 默认 status 走"人话一句"，不再 dump 工作区/能力/边界。
    # raw 报告走 "工具箱 debug status" 单独看。
    assert result.reply == "工具箱正常。"
    assert "仅 owner 私聊可用" not in result.reply
    assert "能力：" not in result.reply
    assert "owner_private_only=" not in result.reply
    assert "[owner_toolbox]" not in result.reply


def test_toolbox_non_owner_private_is_blocked_without_internal_details(tmp_path: Path) -> None:
    result = handle_owner_engineering_toolbox_message(
        _msg("工具箱 status", uid="10086", is_owner=False),
        _cfg(),
        project_root=tmp_path,
    )

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "owner_only"
    assert result.gate is not None and result.gate.actor == "private_non_owner"
    assert "owner 私聊" in result.reply
    assert "owner_private_only" not in result.reply
    assert "workspace_root=" not in result.reply
    assert "TaskRequest" not in result.reply


def test_toolbox_group_trigger_is_silent_not_visible(tmp_path: Path) -> None:
    result = handle_owner_engineering_toolbox_message(
        _msg("工具箱 status", channel="group", is_owner=True),
        _cfg(),
        project_root=tmp_path,
    )

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "private_only"
    assert result.reply == ""
    assert result.gate is not None and result.gate.actor == "group"


def test_toolbox_path_traversal_and_sensitive_paths_are_blocked(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "safe readme")
    _write(tmp_path / ".env", "TOKEN=super-secret")
    _write(tmp_path / "config" / "api_key.txt", "secret body")
    _write(tmp_path / "secrets" / "note.txt", "secret body")

    traversal = handle_owner_engineering_toolbox_message(_msg("工具箱 read ../README.md"), _cfg(), project_root=tmp_path)
    dot_env = handle_owner_engineering_toolbox_message(_msg("工具箱 read .env"), _cfg(), project_root=tmp_path)
    key_file = handle_owner_engineering_toolbox_message(_msg("工具箱 read config/api_key.txt"), _cfg(), project_root=tmp_path)
    secrets_dir = handle_owner_engineering_toolbox_message(_msg("工具箱 list secrets"), _cfg(), project_root=tmp_path)

    assert traversal.allowed is False and traversal.reason == "path_traversal_blocked" and "受控工作区" in traversal.reply
    assert dot_env.allowed is False and dot_env.reason.startswith("sensitive_path_blocked") and "敏感" in dot_env.reply
    assert key_file.allowed is False and key_file.reason.startswith("sensitive_path_blocked") and "敏感" in key_file.reply
    assert secrets_dir.allowed is False and secrets_dir.reason.startswith("sensitive_path_blocked") and "敏感" in secrets_dir.reply
    assert "super-secret" not in dot_env.reply
    assert "secret body" not in key_file.reply


def test_toolbox_read_file_line_and_size_limits(tmp_path: Path) -> None:
    body = "\n".join(f"line-{idx}-xxxxxxxx" for idx in range(1, 20))
    _write(tmp_path / "docs" / "demo.md", body)

    result = handle_owner_engineering_toolbox_message(
        _msg("工具箱 read docs/demo.md 2 99"),
        _cfg(owner_engineering_toolbox_max_read_lines=3, owner_engineering_toolbox_max_read_bytes=50),
        project_root=tmp_path,
    )

    assert result.allowed is True
    assert result.execution is not None and result.execution.status == "ok"
    assert result.execution.data["returned_lines"] in {2, 3}
    assert result.execution.data["byte_truncated"] is True
    assert "这是 docs/demo.md 的内容" in result.reply
    assert "returned_lines=" not in result.reply
    assert "2: line-2" in result.reply
    assert "5: line-5" not in result.reply


def test_toolbox_grep_result_limit_and_sensitive_file_skip(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "needle one\nneedle two\nneedle three\n")
    _write(tmp_path / "b.txt", "needle four\n")
    _write(tmp_path / ".env", "needle TOKEN=super-secret\n")
    _write(tmp_path / "api_key.txt", "needle secret body\n")

    result = handle_owner_engineering_toolbox_message(
        _msg("工具箱 grep needle ."),
        _cfg(owner_engineering_toolbox_max_grep_results=2),
        project_root=tmp_path,
    )

    assert result.allowed is True
    assert result.execution is not None and result.execution.data["results"] == 2
    assert result.execution.data["truncated"] is True
    assert result.execution.data["skipped_sensitive"] >= 1
    assert "找到了 2 条" in result.reply
    assert "results=" not in result.reply
    assert "super-secret" not in result.reply
    assert "secret body" not in result.reply
    assert ".env" not in result.reply
    assert "api_key.txt" not in result.reply


def test_toolbox_write_shell_python_are_real_when_enabled(tmp_path: Path) -> None:
    write_result = handle_owner_engineering_toolbox_message(
        _msg("工具箱 write docs/new.txt hello-world"),
        _cfg(),
        project_root=tmp_path,
    )
    shell_result = handle_owner_engineering_toolbox_message(_msg("工具箱 shell echo shell-ok"), _cfg(), project_root=tmp_path)
    python_result = handle_owner_engineering_toolbox_message(_msg("工具箱 python print(1)"), _cfg(), project_root=tmp_path)

    assert write_result.allowed is True
    assert write_result.execution is not None
    assert write_result.execution.status == "ok"
    assert write_result.execution.real_write is True
    assert "已写入 docs/new.txt" in write_result.reply
    assert "real_write=" not in write_result.reply
    assert (tmp_path / "docs" / "new.txt").read_text(encoding="utf-8") == "hello-world"

    assert shell_result.allowed is True
    assert shell_result.execution is not None and shell_result.execution.real_execute is True
    assert "shell-ok" in shell_result.reply

    assert python_result.allowed is True
    assert python_result.execution is not None and python_result.execution.real_execute is True
    assert "1" in python_result.reply


def test_toolbox_pack_writes_archive_and_sha256(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.py", "print('a')\n")
    _write(tmp_path / "src" / "b.py", "print('b')\n")

    result = handle_owner_engineering_toolbox_message(_msg("工具箱 pack src"), _cfg(), project_root=tmp_path)

    assert result.allowed is True
    assert result.execution is not None and result.execution.real_write is True
    assert "已打包" in result.reply
    assert "SHA256" in result.reply
    assert "pack_archive" not in result.reply
    assert "sha256=" not in result.reply
    archive_rel = result.execution.data["archive"]
    assert (tmp_path / archive_rel).exists()
    assert (tmp_path / archive_rel).with_suffix((tmp_path / archive_rel).suffix + ".sha256").exists()
