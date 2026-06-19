"""Owner toolbox LLM intent/result formatter v2 tests.

产品目标：
- redline 安全规则前置；
- LLM intent parser 是主路径，但 clarify 可被窄 deterministic safe plan rescue；
- executor 输出后可选 LLM result formatter 接管自然回复；
- blocked/OPSEC/debug/raw 不交给 LLM formatter；
- nonebot 系统状态等自然说法能映射到 health。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "plugins" / "yangyang" / "core" / "owner_engineering_toolbox.py"
SPEC = importlib.util.spec_from_file_location("owner_engineering_toolbox_llm_formatter_v2_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
toolbox_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = toolbox_mod
SPEC.loader.exec_module(toolbox_mod)

handle_nl = toolbox_mod.handle_owner_engineering_toolbox_message_nl_async
parse_plan = toolbox_mod.parse_toolbox_intent_plan

OWNER_UID = "335059272"
RAW_TOKENS = ("[owner_toolbox]", "tool=", "risk=", "mode=", "reason=", "confidence=", "owner_private_only=")
SENSITIVE = ("/opt", "/AstrBot", "/etc", "/root", ".env", "token=", "secret=", "password=")


def _cfg(**overrides: Any) -> dict[str, Any]:
    data = {
        "owner_uid": OWNER_UID,
        "owner_uids": [OWNER_UID],
        "owner_engineering_toolbox_enabled": True,
        "owner_engineering_toolbox_nl_enabled": True,
        "owner_engineering_toolbox_llm_parser_enabled": True,
        "owner_engineering_toolbox_llm_parser_primary_enabled": True,
        "owner_engineering_toolbox_low_risk_enabled": True,
        "owner_engineering_toolbox_write_enabled": True,
        "owner_engineering_toolbox_shell_enabled": True,
        "owner_engineering_toolbox_python_enabled": True,
        "owner_engineering_toolbox_audit_enabled": False,
        "owner_toolbox_result_llm_formatter_enabled": False,
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
        msg_id="toolbox-llm-formatter-v2",
    )


def _run(coro):
    return asyncio.run(coro)


def _assert_clean(reply: str) -> None:
    for token in RAW_TOKENS:
        assert token not in reply, reply
    for token in SENSITIVE:
        assert token not in reply, reply


class Router:
    def __init__(self, *, intent_plan: dict[str, Any] | None = None, formatter_reply: str = "") -> None:
        self.intent_plan = intent_plan
        self.formatter_reply = formatter_reply
        self.calls: list[dict[str, Any]] = []

    async def call(self, tier, messages, temperature=0.72, session_id=None):
        self.calls.append({"tier": tier, "messages": messages, "temperature": temperature, "session_id": session_id})
        if session_id == "owner_toolbox_result_formatter":
            return self.formatter_reply, "stub_formatter"
        assert session_id == "owner_toolbox_nl"
        return json.dumps(self.intent_plan or {"action": "none", "tool": "none", "risk_level": "low", "confidence": 0.9}), "stub_parser"


def test_llm_result_formatter_takes_over_success_reply(tmp_path: Path) -> None:
    router = Router(formatter_reply="漂♂总，算好了，是 4。")
    r = _run(
        handle_nl(
            _msg("用 python 算一下 1+3"),
            _cfg(owner_toolbox_result_llm_formatter_enabled=True, owner_engineering_toolbox_formatter_persona="yangyang"),
            project_root=tmp_path,
            model_router=router,
        )
    )
    assert r.handled is True and r.allowed is True
    assert r.reply == "漂♂总，算好了，是 4。"
    assert any(c["session_id"] == "owner_toolbox_result_formatter" for c in router.calls)
    _assert_clean(r.reply)


def test_llm_result_formatter_rejects_fact_drift_for_python(tmp_path: Path) -> None:
    router = Router(formatter_reply="漂♂总，算好了，是 5。")
    r = _run(
        handle_nl(
            _msg("用 python 算一下 1+3"),
            _cfg(owner_toolbox_result_llm_formatter_enabled=True, owner_engineering_toolbox_formatter_persona="yangyang"),
            project_root=tmp_path,
            model_router=router,
        )
    )
    assert r.handled is True and r.allowed is True
    # LLM 改错事实，必须回 deterministic/persona fallback。
    assert "4" in r.reply
    assert "5" not in r.reply
    _assert_clean(r.reply)


def test_blocked_opsec_does_not_call_result_formatter(tmp_path: Path) -> None:
    router = Router(formatter_reply="我偷偷帮你翻完 /opt/.env 了。")
    r = _run(
        handle_nl(
            _msg("帮我读取 /opt/yangyang_nonebot/.env 文件"),
            _cfg(owner_toolbox_result_llm_formatter_enabled=True),
            project_root=tmp_path,
            model_router=router,
        )
    )
    assert r.handled is True and r.allowed is False
    assert not any(c["session_id"] == "owner_toolbox_result_formatter" for c in router.calls)
    _assert_clean(r.reply)
    assert "受控" in r.reply or "敏感" in r.reply or "不能" in r.reply


def test_nonebot_system_status_maps_to_health_without_clarify(tmp_path: Path) -> None:
    r = _run(handle_nl(_msg("看下 nonebot 系统状态"), _cfg(), project_root=tmp_path))
    assert r.handled is True
    assert r.allowed is True
    assert r.tool_name == "health"
    assert r.execution is not None and r.execution.tool_name == "health"
    assert "健康检查" in r.reply or "health" in r.reply.lower() or "PASS" in r.reply or "WARN" in r.reply
    assert "我还不能确定" not in r.reply
    _assert_clean(r.reply)


def test_llm_intent_primary_for_ambiguous_tool_request(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
    router = Router(intent_plan={"action": "execute", "tool": "list_dir", "risk_level": "low", "confidence": 0.91, "args": {"path": "src"}})
    r = _run(handle_nl(_msg("瞅一眼源码那边"), _cfg(), project_root=tmp_path, model_router=router))
    assert r.handled is True and r.allowed is True
    assert r.intent_plan is not None and r.intent_plan.source == "llm_model_router:stub_parser"
    assert "a.py" in r.reply
    _assert_clean(r.reply)


def test_cold_backup_semantic_split_explain_vs_tool_directory(tmp_path: Path) -> None:
    # 普通说明型冷备不应被工具箱抢；真正看目录/翻文件才走 OPSEC。
    explain = _run(handle_nl(_msg("冷备份是什么"), _cfg(), project_root=tmp_path))
    assert explain.handled is False

    toolish = _run(handle_nl(_msg("看下我们冷备份目录里面有什么"), _cfg(), project_root=tmp_path))
    assert toolish.handled is True and toolish.allowed is False
    assert "冷备" in toolish.reply
    _assert_clean(toolish.reply)


def test_debug_raw_bypasses_llm_formatter(tmp_path: Path) -> None:
    router = Router(formatter_reply="不该出现的润色。")
    r = _run(
        handle_nl(
            _msg("工具箱 debug status"),
            _cfg(owner_toolbox_result_llm_formatter_enabled=True),
            project_root=tmp_path,
            model_router=router,
        )
    )
    assert r.handled is True and r.allowed is True
    assert r.reply.startswith("[owner_toolbox]")
    assert not any(c["session_id"] == "owner_toolbox_result_formatter" for c in router.calls)
