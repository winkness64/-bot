from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"
SPEC = importlib.util.spec_from_file_location("isaac_agent_bus_p0_trigger_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)
handle = mod.handle_isaac_agent_bus_p0_message


def _owner_private(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="private", is_owner=True)


def test_slash_i_uncle_and_chinese_isaac_trigger_not_english_isaac() -> None:
    english = handle(_owner_private("isaac health"))
    slash_english = handle(_owner_private("/isaac health"))
    bare_i = handle(_owner_private("I叔 health"))
    bare_cn = handle(_owner_private("艾萨克 health"))
    assert english.handled is False
    assert slash_english.handled is False
    assert bare_i.handled is False
    assert bare_cn.handled is False

    lower_i = handle(_owner_private("/i叔 health"))
    upper_i = handle(_owner_private("/I叔 health"))
    cn_name = handle(_owner_private("/艾萨克 health"))
    assert lower_i.handled and lower_i.allowed and lower_i.task_type == "health_report"
    assert upper_i.handled and upper_i.allowed and upper_i.task_type == "health_report"
    assert cn_name.handled and cn_name.allowed and cn_name.task_type == "health_report"


def test_trigger_position_is_prefix_slash_only() -> None:
    prefix = handle(_owner_private("/I叔 health"))
    middle = handle(_owner_private("麻烦 I叔 health 看看"))
    suffix = handle(_owner_private("帮我 health 一下 I叔"))
    assert prefix.handled and prefix.allowed and prefix.task_type == "health_report"
    assert middle.handled is False
    assert suffix.handled is False


def test_uncertain_bare_request_not_regex_fallback() -> None:
    result = handle(_owner_private("I叔 你看这个是不是有问题？"))
    assert result.handled is False
    assert result.reason == "not_isaac_command"
