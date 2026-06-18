"""M3 redo 真机 smoke 断言。

不调用 LLM/ModelRouter，仅走 deterministic + 本地 fallback 路径，对 4 条真机输入
打 owner 私聊 reply，断言：
- 不被安全规则误伤（tmp / python 算式 / status）
- 不出 raw 字段 / 配置单
- 冷备保持 OPSEC，不吐 /opt
- 普通闲聊不触发
- 高风险 / 敏感路径仍然拦截
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
SPEC = importlib.util.spec_from_file_location("owner_engineering_toolbox_m3_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
toolbox_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = toolbox_mod
SPEC.loader.exec_module(toolbox_mod)

handle_nl = toolbox_mod.handle_owner_engineering_toolbox_message_nl_async

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
        msg_id="m3-redo-smoke",
    )


def _run(coro):
    return asyncio.run(coro)


def _assert_no_raw_fields(reply: str) -> None:
    forbidden = [
        "[owner_toolbox]",
        "[owner_toolbox_nl]",
        "tool=",
        "risk=",
        "mode=",
        "owner_private_only=",
        "real_write=",
        "real_execute=",
        "confidence=",
        "reason=",
    ]
    for token in forbidden:
        assert token not in reply, f"reply 泄漏 raw 字段: {token} in {reply!r}"


# ---- 4 条真机 smoke ----


def test_m3_list_tmp_empty_is_natural_and_unblocked(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    r = _run(handle_nl(_msg("帮我看一下 tmp 目录有什么"), _cfg(), project_root=tmp_path))
    assert r.handled is True
    assert r.allowed is True
    assert r.reply == "tmp 目录是空的。"
    _assert_no_raw_fields(r.reply)


def test_m3_list_tmp_with_entries_is_natural(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "a").write_text("a", encoding="utf-8")
    (tmp_path / "tmp" / "b").write_text("b", encoding="utf-8")
    # 用更明确的措辞命中 local fallback 的 list_dir
    r = _run(handle_nl(_msg("帮我看一下 tmp 目录有什么"), _cfg(), project_root=tmp_path))
    assert r.handled is True
    assert r.allowed is True
    assert "tmp" in r.reply and "有" in r.reply
    assert "a" in r.reply and "b" in r.reply
    _assert_no_raw_fields(r.reply)


def test_m3_python_one_plus_one_is_natural(tmp_path: Path) -> None:
    r = _run(handle_nl(_msg("用 python 算一下 1+1"), _cfg(), project_root=tmp_path))
    assert r.handled is True
    assert r.allowed is True
    assert r.reply == "结果是 2。"
    _assert_no_raw_fields(r.reply)


def test_m3_python_expression_variants(tmp_path: Path) -> None:
    # 关键命中："python"/"用python"/"用 python" 都要进 python fallback
    for q in ("用 python 算一下 1+1", "用python算一下 2*3"):
        r = _run(handle_nl(_msg(q), _cfg(), project_root=tmp_path))
        assert r.handled is True, q
        assert r.allowed is True, q
        assert r.reason in {"python_ok"}, q
        assert "结果" in r.reply, q
        _assert_no_raw_fields(r.reply)


def test_m3_cold_backup_clarification_no_opt(tmp_path: Path) -> None:
    r = _run(handle_nl(_msg("看下我们冷备份目录里面有什么"), _cfg(), project_root=tmp_path))
    assert r.handled is True
    assert r.allowed is False
    assert r.execution is None
    assert r.reply == "冷备相关不能直接展开路径；请给相对工作区路径，或走受控交接。"
    _assert_no_raw_fields(r.reply)
    assert "/opt" not in r.reply
    assert "/opt" not in r.raw_reply


def test_m3_status_default_is_one_liner_human(tmp_path: Path) -> None:
    """M3 redo: 默认 status 走"人话一句"，不再是配置单。"""
    r = _run(handle_nl(_msg("工具箱 status"), _cfg(), project_root=tmp_path))
    assert r.handled is True
    assert r.allowed is True
    # 一行人话，不再 dump 工作区/能力/边界
    assert r.reply == "工具箱正常。"
    _assert_no_raw_fields(r.reply)
    # 不再像 OA 风控小黑框
    assert "工作区：" not in r.reply
    assert "能力：" not in r.reply
    assert "边界：" not in r.reply
    assert "仅 owner 私聊可用" not in r.reply


def test_m3_status_debug_still_raw(tmp_path: Path) -> None:
    """debug/raw 路径下保留 raw report，不受影响。"""
    r = _run(handle_nl(_msg("工具箱 debug status"), _cfg(), project_root=tmp_path))
    assert r.handled is True
    assert r.allowed is True
    assert r.reply.startswith("[owner_toolbox]")
    assert "tool=toolbox_status" in r.reply
    assert "risk=" in r.reply


# ---- 闲聊 / 边界 / 高风险 / 敏感路径 ----


def test_m3_ordinary_chat_does_not_trigger(tmp_path: Path) -> None:
    r = _run(handle_nl(_msg("辛苦了，晚上好"), _cfg(), project_root=tmp_path))
    assert r.handled is False
    assert r.reply == ""


def test_m3_high_risk_nl_confirm_only(tmp_path: Path) -> None:
    r = _run(handle_nl(_msg("帮我重启 nonebot 服务"), _cfg(), project_root=tmp_path))
    assert r.handled is True
    assert r.allowed is False
    assert r.execution is None
    assert "高风险" in r.reply or "不能直接执行" in r.reply


def test_m3_sensitive_path_blocked(tmp_path: Path) -> None:
    r = _run(handle_nl(_msg("帮我看一下 /etc/passwd"), _cfg(), project_root=tmp_path))
    assert r.handled is True
    assert r.allowed is False
    assert r.execution is None
    assert "敏感" in r.reply or "受控" in r.reply


def test_m3_opt_path_blocked_before_llm(tmp_path: Path) -> None:
    """opt 路径 + .env + 读取关键词必须在调 LLM 之前直接拦。"""
    calls: list[str] = []

    async def provider(text: str, context: dict[str, Any]) -> dict[str, Any]:
        calls.append(text)
        return {"action": "execute", "tool": "read_file", "risk_level": "low", "confidence": 0.99, "args": {"path": "/opt/yangyang_nonebot/.env"}}

    # 触发句里同时含 opt 绝对路径 + .env + "读取"/"文件" 关键词，确保 redline pre-LLM 命中
    r = _run(handle_nl(_msg("帮我读取 /opt/yangyang_nonebot/.env 文件"), _cfg(), project_root=tmp_path, intent_provider=provider))
    assert calls == [], f"redline 没拦住，LLM 已被调: {calls}"
    assert r.handled is True
    assert r.allowed is False
    assert "/opt" not in r.reply
    assert "受控工作区" in r.reply or "敏感" in r.reply


def test_m3_group_and_non_owner_disabled(tmp_path: Path) -> None:
    g = _run(handle_nl(_msg("工具箱 status", channel="group", is_owner=True), _cfg(), project_root=tmp_path))
    n = _run(handle_nl(_msg("工具箱 status", uid="10086", is_owner=False), _cfg(), project_root=tmp_path))
    assert g.handled is True and g.allowed is False and g.reason == "private_only" and g.reply == ""
    assert n.handled is True and n.allowed is False and n.reason == "owner_only"
    assert "owner 私聊" in n.reply
