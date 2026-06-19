"""Persona Formatter v1 tests for Owner 工程工具箱.

断言原则：不写死完整句子，只锁关键事实、禁止 raw 泄漏、禁止敏感路径泄漏、persona 特征。
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "plugins" / "yangyang" / "core" / "owner_engineering_toolbox.py"
SPEC = importlib.util.spec_from_file_location("owner_engineering_toolbox_persona_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
toolbox_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = toolbox_mod
SPEC.loader.exec_module(toolbox_mod)

handle_nl = toolbox_mod.handle_owner_engineering_toolbox_message_nl_async
format_for_user = toolbox_mod.format_owner_toolbox_result_for_user
normalize_persona = toolbox_mod._normalize_persona

OWNER_UID = "335059272"
RAW_TOKENS = (
    "[owner_toolbox]",
    "[owner_toolbox_nl]",
    "tool=",
    "risk=",
    "mode=",
    "reason=",
    "confidence=",
    "owner_private_only=",
    "real_write=",
    "real_execute=",
)
SENSITIVE_TOKENS = ("/opt", "/AstrBot", "/etc", ".env", "TOKEN=", "token=", "secret=", "password=")


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
        "owner_engineering_toolbox_audit_enabled": False,
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
        msg_id="persona-formatter-v1",
    )


def _run(coro):
    return asyncio.run(coro)


def _assert_no_raw(reply: str) -> None:
    for token in RAW_TOKENS:
        assert token not in reply, f"raw token leaked: {token} in {reply!r}"


def _assert_no_sensitive(reply: str) -> None:
    for token in SENSITIVE_TOKENS:
        assert token not in reply, f"sensitive token leaked: {token} in {reply!r}"


def _assert_short(reply: str, *, max_lines: int = 2, max_chars: int = 120) -> None:
    assert len([line for line in reply.splitlines() if line.strip()]) <= max_lines
    assert len(reply) <= max_chars


def _assert_persona_feature(reply: str, persona: str) -> None:
    if persona == "yangyang":
        assert "漂♂总" in reply or any(word in reply for word in ("这边", "我先", "更稳"))
    elif persona == "yaya":
        assert any(word in reply for word in ("没藏", "清清爽爽", "别硬", "硬看", "硬闯", "踩线", "活着", "能使唤", "没跑偏", "先刹", "别当完成"))
    elif persona == "isaac":
        assert any(word in reply for word in ("：", "已", "未执行", "正常", "为空", "结果"))
        assert "漂♂总" not in reply


def test_normalize_persona_aliases() -> None:
    assert normalize_persona(None) == "default"
    assert normalize_persona("秧秧") == "yangyang"
    assert normalize_persona("娅娅") == "yaya"
    assert normalize_persona("I叔") == "isaac"
    assert normalize_persona("unknown") == "default"


def test_persona_list_tmp_empty_variants(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    replies: dict[str, str] = {}
    for persona in ("default", "yangyang", "yaya", "isaac"):
        r = _run(handle_nl(_msg("帮我看一下 tmp 目录有什么"), _cfg(), project_root=tmp_path, persona=persona))
        assert r.handled is True and r.allowed is True
        replies[persona] = r.reply
        assert "tmp" in r.reply
        assert "空" in r.reply or "没有东西" in r.reply or "无内容" in r.reply
        _assert_no_raw(r.reply)
        _assert_no_sensitive(r.reply)
        _assert_short(r.reply)
        if persona != "default":
            _assert_persona_feature(r.reply, persona)
    assert replies["default"] == "tmp 目录是空的。"
    assert replies["yangyang"] != replies["default"]
    assert replies["yaya"] != replies["default"]


def test_persona_python_one_plus_one_contains_result_and_no_raw(tmp_path: Path) -> None:
    for persona in ("default", "yangyang", "yaya", "isaac"):
        r = _run(handle_nl(_msg("用 python 算一下 1+1"), _cfg(), project_root=tmp_path, persona=persona))
        assert r.handled is True and r.allowed is True
        assert "2" in r.reply
        assert "print" not in r.reply and "python <<<" not in r.reply
        _assert_no_raw(r.reply)
        _assert_no_sensitive(r.reply)
        _assert_short(r.reply)
        if persona != "default":
            _assert_persona_feature(r.reply, persona)


def test_persona_status_normal_is_short_not_config_sheet(tmp_path: Path) -> None:
    for persona in ("default", "yangyang", "yaya", "isaac"):
        r = _run(handle_nl(_msg("工具箱 status"), _cfg(), project_root=tmp_path, persona=persona))
        assert r.handled is True and r.allowed is True
        assert "正常" in r.reply or "活着" in r.reply
        for forbidden in ("工作区", "能力", "边界", "workspace", "allowed_low_risk_tools"):
            assert forbidden not in r.reply
        _assert_no_raw(r.reply)
        _assert_no_sensitive(r.reply)
        _assert_short(r.reply)
        if persona != "default":
            _assert_persona_feature(r.reply, persona)


def test_persona_sensitive_cold_backup_and_production_paths_opsec(tmp_path: Path) -> None:
    cases = [
        "看下我们冷备份目录里面有什么",
        "帮我读取 /opt/yangyang_nonebot/.env 文件",
        "帮我看一下 /etc/passwd",
    ]
    for query in cases:
        for persona in ("default", "yangyang", "yaya", "isaac"):
            r = _run(handle_nl(_msg(query), _cfg(), project_root=tmp_path, persona=persona))
            assert r.handled is True and r.allowed is False
            assert r.execution is None
            assert any(word in r.reply for word in ("不能", "拦", "受控", "相对工作区", "未执行", "不直接"))
            _assert_no_raw(r.reply)
            _assert_no_sensitive(r.reply)
            _assert_short(r.reply, max_chars=150)
            if persona != "default":
                _assert_persona_feature(r.reply, persona)


def test_persona_high_risk_shell_requires_confirm_and_not_execute(tmp_path: Path) -> None:
    for persona in ("default", "yangyang", "yaya", "isaac"):
        r = _run(handle_nl(_msg("执行 sudo systemctl restart nonebot"), _cfg(), project_root=tmp_path, persona=persona))
        assert r.handled is True and r.allowed is False
        assert r.execution is None
        assert any(word in r.reply for word in ("高风险", "确认", "未执行", "停住", "不执行"))
        assert "执行成功" not in r.reply and "已完成" not in r.reply
        _assert_no_raw(r.reply)
        _assert_no_sensitive(r.reply)
        _assert_short(r.reply, max_chars=140)
        if persona != "default":
            _assert_persona_feature(r.reply, persona)


def test_persona_error_and_timeout_are_not_reported_as_success(tmp_path: Path) -> None:
    fail = _run(handle_nl(_msg("工具箱 python raise Exception('boom')"), _cfg(), project_root=tmp_path, persona="yaya"))
    assert fail.handled is True and fail.allowed is False
    assert any(word in fail.reply for word in ("失败", "没跑成", "未完成"))
    assert "成功" not in fail.reply and "搞定" not in fail.reply
    _assert_no_raw(fail.reply)
    _assert_no_sensitive(fail.reply)

    timeout = _run(
        handle_nl(
            _msg("工具箱 shell python3 -c 'import time; time.sleep(2)'"),
            _cfg(owner_engineering_toolbox_timeout_seconds=1),
            project_root=tmp_path,
            persona="yangyang",
        )
    )
    assert timeout.handled is True and timeout.allowed is False
    assert "超时" in timeout.reply or "没拿到结果" in timeout.reply
    assert "成功" not in timeout.reply and "已完成" not in timeout.reply
    _assert_no_raw(timeout.reply)
    _assert_no_sensitive(timeout.reply)


def test_debug_status_keeps_raw_even_with_persona(tmp_path: Path) -> None:
    r = _run(handle_nl(_msg("工具箱 debug status"), _cfg(), project_root=tmp_path, persona="yaya"))
    assert r.handled is True and r.allowed is True
    assert r.reply.startswith("[owner_toolbox]")
    assert "tool=toolbox_status" in r.reply
    assert "risk=" in r.reply


def test_formatter_raw_report_persona_scrubs_when_explicitly_requested() -> None:
    raw = "[owner_toolbox] tool=read_file status=blocked reason=production_path_blocked risk=high owner_private_only=true\n/opt/yangyang_nonebot/.env TOKEN=abc"
    reply = format_for_user(raw_report=raw, persona="yangyang")
    assert not reply.startswith("[owner_toolbox]")
    _assert_no_raw(reply)
    _assert_no_sensitive(reply)
    assert "受控" in reply or "不能" in reply or "未执行" in reply
