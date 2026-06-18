from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "plugins" / "yangyang" / "core" / "owner_toolbox_light.py"
SPEC = importlib.util.spec_from_file_location("owner_toolbox_light_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
toolbox_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = toolbox_mod
SPEC.loader.exec_module(toolbox_mod)

build_owner_toolbox_tools = toolbox_mod.build_owner_toolbox_tools
execute_owner_toolbox_tool = toolbox_mod.execute_owner_toolbox_tool
handle_owner_toolbox_light_message = toolbox_mod.handle_owner_toolbox_light_message
handle_slash_command = toolbox_mod.handle_slash_command
is_owner_private = toolbox_mod.is_owner_private
parse_slash_command = toolbox_mod.parse_slash_command

OWNER_UID = "335059272"


def _msg(text: str, *, uid: str = OWNER_UID, channel: str = "private", is_owner: bool | None = None):
    return SimpleNamespace(
        text=text,
        raw_content=text,
        uid=uid,
        user_id=uid,
        channel=channel,
        group_id="137918147" if channel == "group" else "",
        is_owner=(uid == OWNER_UID if is_owner is None else is_owner),
    )


def _cfg(tmp_path: Path) -> dict:
    return {
        "owner_uid": OWNER_UID,
        "owner_uids": [OWNER_UID],
        "owner_toolbox_light_workspace_root": str(tmp_path),
        "owner_toolbox_light_timeout_seconds": 5,
        "owner_toolbox_light_max_output_chars": 4000,
    }


def _run(coro):
    return asyncio.run(coro)


def test_parse_slash_command_registered_only() -> None:
    cmd = parse_slash_command("  /toolbox status")
    assert cmd is not None
    assert cmd.token == "toolbox"
    assert cmd.rest == "status"
    assert cmd.argv == ("status",)

    assert parse_slash_command("/root/xxx 记一下") is None
    assert parse_slash_command("我今天重启了电脑") is None
    assert parse_slash_command("/unknown status") is None
    assert parse_slash_command("/toolboxStatus") is None


def test_owner_private_visible_group_and_non_owner_not_visible(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert is_owner_private(_msg("/toolbox status"), cfg) is True
    assert is_owner_private(_msg("/toolbox status", channel="group"), cfg) is False
    assert is_owner_private(_msg("/toolbox status", uid="10086", is_owner=False), cfg) is False

    group_result = _run(handle_owner_toolbox_light_message(_msg("/toolbox status", channel="group"), cfg, project_root=tmp_path))
    assert group_result.handled is False
    assert group_result.reason == "not_owner_private"

    non_owner_result = _run(handle_owner_toolbox_light_message(_msg("/toolbox status", uid="10086", is_owner=False), cfg, project_root=tmp_path))
    assert non_owner_result.handled is False
    assert non_owner_result.reason == "not_owner_private"


def test_slash_root_and_plain_restart_chat_do_not_trigger(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    rootish = _run(handle_owner_toolbox_light_message(_msg("/root/xxx 记一下"), cfg, project_root=tmp_path))
    assert rootish.handled is False
    assert rootish.reason == "no_tool_intent"

    chat = _run(handle_owner_toolbox_light_message(_msg("我今天重启了电脑"), cfg, project_root=tmp_path))
    assert chat.handled is False
    assert chat.reason == "no_tool_intent"


def test_executor_status_list_read_python_shell_write_pack(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "README.md").write_text("hello\nworld\n", encoding="utf-8")
    (tmp_path / "logs" / "app.log").write_text("a\nb\nc\n", encoding="utf-8")

    status = execute_owner_toolbox_tool("status", {}, cfg, project_root=tmp_path)
    assert status.handled and status.allowed and status.tool_name == "status"
    assert "status" in status.data["tools"]

    listed = execute_owner_toolbox_tool("list", {"path": "."}, cfg, project_root=tmp_path)
    assert listed.allowed and "README.md" in listed.reply

    read = execute_owner_toolbox_tool("read", {"path": "README.md", "lines": 1}, cfg, project_root=tmp_path)
    assert read.allowed and "hello" in read.reply

    log_tail = execute_owner_toolbox_tool("log_tail", {"path": "logs/app.log", "lines": 2}, cfg, project_root=tmp_path)
    assert log_tail.allowed and "b" in log_tail.reply and "c" in log_tail.reply

    py = execute_owner_toolbox_tool("python", {"code": "1+3"}, cfg, project_root=tmp_path)
    assert py.allowed and "4" in py.reply

    sh = execute_owner_toolbox_tool("shell", {"command": "pwd"}, cfg, project_root=tmp_path)
    assert sh.allowed and str(tmp_path) in sh.reply

    write = execute_owner_toolbox_tool("write", {"path": "notes/a.txt", "content": "ok"}, cfg, project_root=tmp_path)
    assert write.allowed and (tmp_path / "notes" / "a.txt").read_text(encoding="utf-8") == "ok"

    pack = execute_owner_toolbox_tool("pack", {"paths": ["README.md", "notes"], "output": "dist/test.tar.gz"}, cfg, project_root=tmp_path)
    assert pack.allowed and (tmp_path / "dist" / "test.tar.gz").exists()


def test_handle_slash_command_toolbox_status(tmp_path: Path) -> None:
    result = _run(handle_slash_command(_msg("/toolbox status"), _cfg(tmp_path), project_root=tmp_path))
    assert result.handled is True
    assert result.allowed is True
    assert result.tool_name == "status"
    assert result.reply == "工具箱正常。"


def test_build_owner_toolbox_tools_contains_light_tools() -> None:
    tools = build_owner_toolbox_tools()
    names = {item["name"] for item in tools}
    assert {"status", "list", "read", "log_tail", "python", "shell", "write", "pack", "isaac_p0"}.issubset(names)


# ---------------------------------------------------------------------------
# Owner-private host-filesystem smoke tests (no workspace sandbox).
# Mirrors the owner 私聊 "看下冷备份有啥文件" regression: absolute host
# paths must be accepted by the executor, the executor must NOT synthesize
# `outside_workspace`, and group / non-owner callers must still be locked out.
# ---------------------------------------------------------------------------


def test_list_absolute_path_outside_default_cwd_is_allowed(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cold = tmp_path.parent / "yangyang_cold_backup"
    if cold.exists():
        for child in cold.iterdir():
            if child.is_file():
                child.unlink()
    else:
        cold.mkdir()
    (cold / "README.txt").write_text("x", encoding="utf-8")
    try:
        result = execute_owner_toolbox_tool("list", {"path": str(cold)}, cfg, project_root=tmp_path)
        assert result.allowed is True, f"expected allowed, got reason={result.reason}"
        assert "README.txt" in result.reply
        assert "outside_workspace" not in result.reply
    finally:
        for child in cold.iterdir():
            if child.is_file():
                child.unlink()
        try:
            cold.rmdir()
        except OSError:
            pass


def test_read_absolute_path_outside_default_cwd_is_allowed(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cold = tmp_path.parent / "yangyang_cold_backup_read"
    cold.mkdir()
    (cold / "note.txt").write_text("hello from cold backup", encoding="utf-8")
    try:
        result = execute_owner_toolbox_tool("read", {"path": str(cold / "note.txt")}, cfg, project_root=tmp_path)
        assert result.allowed is True
        assert "hello from cold backup" in result.reply
    finally:
        for child in cold.iterdir():
            if child.is_file():
                child.unlink()
        cold.rmdir()


def test_shell_command_outside_default_cwd_is_allowed(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cold = tmp_path.parent / "yangyang_cold_backup_shell"
    if cold.exists():
        for child in cold.iterdir():
            if child.is_file():
                child.unlink()
        cold.rmdir()
    cold.mkdir()
    try:
        result = execute_owner_toolbox_tool(
            "shell",
            {"command": f"ls {cold}"},
            cfg,
            project_root=tmp_path,
        )
        assert result.allowed is True, f"expected allowed, got reason={result.reason} reply={result.reply}"
    finally:
        try:
            cold.rmdir()
        except OSError:
            pass


def test_group_and_non_owner_still_locked_out(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    group_msg = _msg("/toolbox list /tmp", channel="group")
    group_result = _run(handle_owner_toolbox_light_message(group_msg, cfg, project_root=tmp_path))
    assert group_result.handled is False
    assert group_result.reason == "not_owner_private"

    non_owner_msg = _msg("/toolbox list /tmp", uid="10086", is_owner=False)
    non_owner_result = _run(handle_owner_toolbox_light_message(non_owner_msg, cfg, project_root=tmp_path))
    assert non_owner_result.handled is False
    assert non_owner_result.reason == "not_owner_private"


def test_tool_metadata_describes_host_filesystem_not_workspace() -> None:
    tools = {item["name"]: item for item in build_owner_toolbox_tools()}
    for name in ("list", "read", "log_tail", "write", "pack"):
        desc = str(tools[name]["description"]).lower()
        # description must not assert a workspace sandbox; "no workspace sandbox" is fine
        assert "under the workspace" not in desc, f"{name} description still claims a workspace: {desc!r}"
        assert ("host" in desc) or ("absolute" in desc), f"{name} description should mention host/absolute: {desc!r}"
    for name in ("shell", "python"):
        desc = str(tools[name]["description"]).lower()
        # shell/python descriptions must explicitly mark sandbox OFF and no keyword gate
        assert ("no workspace sandbox" in desc) or ("full host" in desc), f"{name} description must mark no-sandbox: {desc!r}"
        assert "no keyword safety valve" in desc, f"{name} description must declare no keyword gate: {desc!r}"


def test_parse_isaac_slash_aliases_and_bare_not_slash() -> None:
    lower = parse_slash_command("/i叔 health")
    upper = parse_slash_command("/I叔 health")
    chinese = parse_slash_command("/艾萨克 health")
    assert lower is not None and lower.token == "i叔" and lower.rest == "health"
    assert upper is not None and upper.token == "i叔" and upper.rest == "health"
    assert chinese is not None and chinese.token == "艾萨克" and chinese.rest == "health"
    assert parse_slash_command("I叔 帮我看看状态") is None
    assert parse_slash_command("艾萨克 health") is None
    assert parse_slash_command("~i叔 health") is None


def test_owner_private_isaac_slash_aliases_trigger_p0(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    for text in ("/i叔 health", "/I叔 health", "/艾萨克 health"):
        result = _run(handle_owner_toolbox_light_message(_msg(text), cfg, project_root=tmp_path))
        assert result.handled is True
        assert result.allowed is True
        assert result.tool_name == "isaac_p0"
        assert result.reason == "pass"
        assert result.data["task_type"] == "health_report"
        assert "I叔 P0 闭环已跑通" in result.reply


def test_owner_private_bare_isaac_not_regex_fallback(tmp_path: Path) -> None:
    result = _run(handle_owner_toolbox_light_message(_msg("I叔 帮我看看状态"), _cfg(tmp_path), project_root=tmp_path))
    assert result.handled is False
    assert result.reason == "no_tool_intent"


def test_group_and_non_owner_isaac_slash_no_real_execution(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    group_result = _run(handle_owner_toolbox_light_message(_msg("/i叔 health", channel="group"), cfg, project_root=tmp_path))
    non_owner_result = _run(handle_owner_toolbox_light_message(_msg("/i叔 health", uid="10086", is_owner=False), cfg, project_root=tmp_path))
    assert group_result.handled is False
    assert group_result.reason == "not_owner_private"
    assert non_owner_result.handled is False
    assert non_owner_result.reason == "not_owner_private"
