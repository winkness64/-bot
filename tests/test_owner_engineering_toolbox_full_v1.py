from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "owner_engineering_toolbox.py"
SPEC = importlib.util.spec_from_file_location("owner_engineering_toolbox_full_v1_under_test", MODULE_PATH)
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


def _msg(text: str, *, uid: str = OWNER_UID, channel: str = "private", is_owner: bool | None = None):
    return SimpleNamespace(
        text=text,
        raw_content=text,
        uid=uid,
        channel=channel,
        is_owner=(uid == OWNER_UID if is_owner is None else is_owner),
        group_id="137918147" if channel == "group" else "",
        msg_id="toolbox-full-test-msg",
    )


def test_full_v1_owner_gate_pass_group_and_non_owner_blocked(tmp_path: Path) -> None:
    command = parse_toolbox_command("工具箱 shell echo ok")
    gate = evaluate_toolbox_gate(command, _msg("工具箱 shell echo ok"), _cfg(), project_root=tmp_path)
    assert gate.allowed is True
    assert gate.actor == "owner_private"
    assert gate.mode == "execute"

    group = handle_owner_engineering_toolbox_message(_msg("工具箱 shell echo nope", channel="group", is_owner=True), _cfg(), project_root=tmp_path)
    assert group.handled is True and group.allowed is False and group.reply == ""

    non_owner = handle_owner_engineering_toolbox_message(_msg("工具箱 shell echo nope", uid="10086", is_owner=False), _cfg(), project_root=tmp_path)
    assert non_owner.handled is True and non_owner.allowed is False
    assert "owner 私聊" in non_owner.reply
    assert "owner_private_only" not in non_owner.reply
    assert "workspace_root=" not in non_owner.reply


def test_full_v1_shell_and_python_really_execute_and_timeout(tmp_path: Path) -> None:
    shell = handle_owner_engineering_toolbox_message(_msg("工具箱 shell printf toolbox-shell-ok"), _cfg(), project_root=tmp_path)
    assert shell.allowed is True
    assert shell.execution is not None and shell.execution.real_execute is True
    assert "toolbox-shell-ok" in shell.reply

    py = handle_owner_engineering_toolbox_message(_msg("工具箱 python <<<\nprint('toolbox-python-ok')\n>>>"), _cfg(), project_root=tmp_path)
    assert py.allowed is True
    assert py.execution is not None and py.execution.real_execute is True
    assert "toolbox-python-ok" in py.reply

    timeout = handle_owner_engineering_toolbox_message(
        _msg("工具箱 python <<<\nimport time\ntime.sleep(2)\nprint('late')\n>>>"),
        _cfg(owner_engineering_toolbox_timeout_seconds=1),
        project_root=tmp_path,
    )
    assert timeout.execution is not None
    assert timeout.execution.status == "timeout"
    assert "执行超时" in timeout.reply
    assert "timeout=true" not in timeout.reply
    assert "late" not in timeout.reply


def test_full_v1_write_read_append_edit_really_write(tmp_path: Path) -> None:
    write = handle_owner_engineering_toolbox_message(_msg("工具箱 write docs/demo.txt <<<\nhello\n>>>"), _cfg(), project_root=tmp_path)
    assert write.allowed is True and (tmp_path / "docs" / "demo.txt").read_text(encoding="utf-8") == "hello"

    append = handle_owner_engineering_toolbox_message(_msg("工具箱 append docs/demo.txt <<<\n world\n>>>"), _cfg(), project_root=tmp_path)
    assert append.allowed is True and (tmp_path / "docs" / "demo.txt").read_text(encoding="utf-8") == "hello world"

    read = handle_owner_engineering_toolbox_message(_msg("工具箱 read docs/demo.txt 1 5"), _cfg(), project_root=tmp_path)
    assert read.allowed is True and "hello world" in read.reply

    edit = handle_owner_engineering_toolbox_message(
        _msg("工具箱 edit docs/demo.txt <<<\nOLD\nhello world\nOLD\nNEW\nHELLO\nNEW\n>>>"),
        _cfg(),
        project_root=tmp_path,
    )
    assert edit.allowed is True
    assert (tmp_path / "docs" / "demo.txt").read_text(encoding="utf-8") == "HELLO"


def test_full_v1_mkdir_rm_trash_pack_and_sha256(tmp_path: Path) -> None:
    mkdir = handle_owner_engineering_toolbox_message(_msg("工具箱 mkdir build/out"), _cfg(), project_root=tmp_path)
    assert mkdir.allowed is True and (tmp_path / "build" / "out").is_dir()
    (tmp_path / "build" / "out" / "a.txt").write_text("pack-me", encoding="utf-8")

    digest = handle_owner_engineering_toolbox_message(_msg("工具箱 sha256 build/out/a.txt"), _cfg(), project_root=tmp_path)
    assert digest.allowed is True and "SHA256" in digest.reply and "sha256=" not in digest.reply

    pack = handle_owner_engineering_toolbox_message(_msg("工具箱 pack build/out"), _cfg(), project_root=tmp_path)
    assert pack.allowed is True
    assert pack.execution is not None and pack.execution.real_write is True
    archive_rel = pack.execution.data["archive"]
    archive_path = tmp_path / archive_rel
    assert archive_path.exists() and archive_path.suffixes[-2:] == [".tar", ".gz"]
    assert archive_path.with_suffix(archive_path.suffix + ".sha256").exists()
    with tarfile.open(archive_path, "r:gz") as tf:
        assert "build/out/a.txt" in tf.getnames()

    rm = handle_owner_engineering_toolbox_message(_msg("工具箱 rm build/out/a.txt"), _cfg(), project_root=tmp_path)
    assert rm.allowed is True
    assert not (tmp_path / "build" / "out" / "a.txt").exists()
    assert list((tmp_path / ".toolbox_trash").glob("*_a.txt"))



def test_full_v1_shell_python_path_guards_block_escape_sensitive_and_opt(tmp_path: Path) -> None:
    shell_opt = handle_owner_engineering_toolbox_message(_msg("工具箱 shell cat /opt/yangyang_nonebot/.env"), _cfg(), project_root=tmp_path)
    shell_escape = handle_owner_engineering_toolbox_message(_msg("工具箱 shell cat /bin/ls"), _cfg(), project_root=tmp_path)
    shell_traversal = handle_owner_engineering_toolbox_message(_msg("工具箱 shell cat ../x.txt"), _cfg(), project_root=tmp_path)
    shell_home = handle_owner_engineering_toolbox_message(_msg("工具箱 shell cat $HOME/.bashrc"), _cfg(), project_root=tmp_path)
    py_sensitive = handle_owner_engineering_toolbox_message(_msg("工具箱 python <<<\nprint(open('.env').read())\n>>>"), _cfg(), project_root=tmp_path)

    assert shell_opt.allowed is False and shell_opt.reason == "production_path_blocked" and "受控工作区" in shell_opt.reply
    assert shell_escape.allowed is False and shell_escape.reason == "path_escape_blocked" and "受控工作区" in shell_escape.reply
    assert shell_traversal.allowed is False and shell_traversal.reason == "path_traversal_blocked" and "受控工作区" in shell_traversal.reply
    assert shell_home.allowed is False and shell_home.reason == "path_escape_blocked" and "受控工作区" in shell_home.reply
    assert py_sensitive.allowed is False and py_sensitive.reason.startswith("sensitive_path_blocked") and "敏感" in py_sensitive.reply

def test_full_v1_path_opt_sensitive_and_audit(tmp_path: Path) -> None:
    (tmp_path / "safe.txt").write_text("safe", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (tmp_path / "api_key.txt").write_text("secret body", encoding="utf-8")

    traversal = handle_owner_engineering_toolbox_message(_msg("工具箱 read ../safe.txt"), _cfg(), project_root=tmp_path)
    opt = handle_owner_engineering_toolbox_message(_msg("工具箱 read /opt/yangyang_nonebot/config.py"), _cfg(), project_root=tmp_path)
    env = handle_owner_engineering_toolbox_message(_msg("工具箱 read .env"), _cfg(), project_root=tmp_path)
    key = handle_owner_engineering_toolbox_message(_msg("工具箱 write api_key.txt <<<\nnope\n>>>"), _cfg(), project_root=tmp_path)

    assert traversal.allowed is False and traversal.reason == "path_traversal_blocked" and "受控工作区" in traversal.reply
    assert opt.allowed is False and opt.reason == "production_path_blocked" and "受控工作区" in opt.reply
    assert env.allowed is False and env.reason.startswith("sensitive_path_blocked") and "敏感" in env.reply and "secret" not in env.reply.lower()
    assert key.allowed is False and key.reason.startswith("sensitive_path_blocked") and "敏感" in key.reply

    ok = handle_owner_engineering_toolbox_message(_msg("工具箱 shell echo audit-ok"), _cfg(), project_root=tmp_path)
    assert ok.allowed is True
    audit_path = tmp_path / "logs" / "owner_engineering_toolbox_audit.jsonl"
    assert audit_path.exists()
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(item.get("tool") == "shell" and item.get("success") is True for item in records)
    assert all("secret body" not in json.dumps(item, ensure_ascii=False) for item in records)
