"""C1 保险丝 Provider 验证：6 项全 mock，不连真 API"""

import asyncio, os, sys
from unittest.mock import AsyncMock, MagicMock

# mock nonebot.log + 全量mock nonebot包
import types, logging
_nb = types.ModuleType("nonebot")
_nb.__path__ = []
_nb.log = types.ModuleType("nonebot.log")
_nb.log.logger = logging.getLogger("test_c1")
_nb.on_message = lambda *a, **kw: None
sys.modules["nonebot"] = _nb
sys.modules["nonebot.log"] = _nb.log

# 另外还需要mock nonebot.plugin等可能的导入路径
_nb_plugin = types.ModuleType("nonebot.plugin")
_nb_plugin.require = lambda *a: None
sys.modules["nonebot.plugin"] = _nb_plugin
_nb_rule = types.ModuleType("nonebot.rule")
_nb_rule.Rule = lambda *a: None
sys.modules["nonebot.rule"] = _nb_rule

# 用exec直接加载model_router.py，不走__init__.py路径
import importlib.util
from pathlib import Path as _P0Path
_model_router_path = (
    _P0Path(__file__).resolve().parents[1]
    / "src/plugins/yangyang/core/model_router.py"
)
_spec = importlib.util.spec_from_file_location(
    "model_router_core",
    str(_model_router_path)
)
_mr_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mr_mod)
ModelRouter = _mr_mod.ModelRouter


class MockCfg:
    def __init__(self, d):
        self._d = d
    def get(self, path, default=None):
        parts = path.split(".")
        cur = self._d
        for p in parts:
            if isinstance(cur, dict):
                cur = cur.get(p, {})
            else:
                return default
        return cur if cur != {} else default
    def get_bool(self, path, default=False):
        v = self.get(path, None)
        return default if v is None else bool(v)


MSGS = [{"role": "user", "content": "你好"}]


def _mock_client(return_text: str):
    c = AsyncMock()
    r = MagicMock()
    r.choices = [MagicMock()]
    r.choices[0].message.content = return_text
    c.chat.completions.create = AsyncMock(return_value=r)
    return c


def _mock_client_error(error_text: str):
    return AsyncMock(
        chat=MagicMock(
            completions=MagicMock(
                create=AsyncMock(side_effect=Exception(error_text))
            )
        )
    )


def _base_cfg(tier_enabled: dict, api_key="sk"):
    models = {
        "v4_flash": {"enabled": False, "model": "deepseek-v4-flash"},
        "v4_pro": {"enabled": False, "model": "deepseek-v4-pro"},
        "gpt_5_5": {"enabled": False, "model": "gpt-5.5"},
    }
    models.update(tier_enabled)
    return MockCfg({"models": models, "api": {"api_key": api_key, "base_url": "https://x"}})


async def test_v4_flash_normal():
    r = ModelRouter(_base_cfg({"v4_flash": {"enabled": True}}))
    r._get_client = MagicMock(return_value=_mock_client("正常回复"))
    text, tier = await r.call("v4_flash", MSGS)
    assert "正常回复" in text
    assert tier == "v4_flash"
    print("✅ 1/6 V4 Flash 正常回复 → PASS")


async def test_v4_flash_sensitive():
    r = ModelRouter(_base_cfg({"v4_flash": {"enabled": True}}))
    r._get_client = MagicMock(return_value=_mock_client_error("sensitive_words_detected"))
    text, tier = await r.call("v4_flash", MSGS)
    assert tier == "local_safe_template", f"expected local_safe_template got {tier}"
    print(f"✅ 2/6 V4 Flash + 敏感词 → tier={tier} PASS")


async def test_gpt_5_5():
    r = ModelRouter(_base_cfg({"v4_flash": {"enabled": False}, "gpt_5_5": {"enabled": True}}))
    r._get_client = MagicMock(return_value=_mock_client("GPT-5.5回复"))
    text, tier = await r.call("gpt_5_5", MSGS)
    assert "GPT-5.5回复" in text
    assert tier == "gpt_5_5"

    r2 = ModelRouter(_base_cfg({"v4_flash": {"enabled": False}, "gpt_5_5": {"enabled": True}}))
    r2._get_client = MagicMock(return_value=_mock_client_error("content_filter"))
    t2, ti2 = await r2.call("gpt_5_5", MSGS)
    assert ti2 == "local_safe_template"
    print(f"✅ 3/6 GPT-5.5 正常+sensitive → normal={tier} safe={ti2} PASS")


async def test_v4_pro():
    r = ModelRouter(_base_cfg({"v4_flash": {"enabled": False}, "v4_pro": {"enabled": True}}))
    r._get_client = MagicMock(return_value=_mock_client("V4Pro回复"))
    text, tier = await r.call("v4_pro", MSGS)
    assert "V4Pro回复" in text
    assert tier == "v4_pro"
    print(f"✅ 4/6 V4 Pro 正常回复 → tier={tier} PASS")


async def test_dry_run():
    os.environ["YANGYANG_DRY_RUN"] = "1"
    r = ModelRouter(_base_cfg({"v4_flash": {"enabled": True}}))
    text, tier = await r.call("v4_flash", MSGS)
    assert "[dry_run]" in text
    assert tier == "dry_run"
    del os.environ["YANGYANG_DRY_RUN"]
    print(f"✅ 5/6 dry_run 模式 → tier={tier} PASS")


async def test_all_tiers_disabled():
    r = ModelRouter(_base_cfg({}))
    text, tier = await r.call("v4_flash", MSGS)
    assert tier == "local_safe_template", f"expected local_safe_template got {tier}"
    print(f"✅ 6/6 全部 provider 禁用 → tier={tier} PASS")


async def main():
    tests = [
        test_v4_flash_normal(),
        test_v4_flash_sensitive(),
        test_gpt_5_5(),
        test_v4_pro(),
        test_dry_run(),
        test_all_tiers_disabled(),
    ]
    for t in tests:
        await t
    print(f"\n🎯 全部 {len(tests)} 项验证通过！")


if __name__ == "__main__":
    asyncio.run(main())
