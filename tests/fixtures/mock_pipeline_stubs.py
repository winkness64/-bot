from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
PLUGIN_ROOT = SRC_ROOT / "plugins" / "yangyang"


def install_nonebot_stubs() -> None:
    """在未安装 nonebot/onebot 时提供最小桩模块。"""
    nonebot_mod = types.ModuleType("nonebot")
    log_mod = types.ModuleType("nonebot.log")
    rule_mod = types.ModuleType("nonebot.rule")
    adapters_mod = types.ModuleType("nonebot.adapters")
    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
    apscheduler_mod = types.ModuleType("apscheduler")
    apscheduler_schedulers_mod = types.ModuleType("apscheduler.schedulers")
    apscheduler_asyncio_mod = types.ModuleType("apscheduler.schedulers.asyncio")

    logger = logging.getLogger("mock_nonebot")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    class GroupMessageEvent:  # pragma: no cover - stub type
        pass

    class PrivateMessageEvent:  # pragma: no cover - stub type
        pass

    class Bot:  # pragma: no cover - stub type
        pass

    class Rule:
        def __init__(self, func):
            self.func = func

    class _FakeMatcher:
        def handle(self):
            def deco(func):
                return func
            return deco

    class _FakeAppState:
        pass

    class _FakeApp:
        def __init__(self):
            self.state = _FakeAppState()

        def post(self, *args, **kwargs):
            def deco(func):
                return func
            return deco

        def get(self, *args, **kwargs):
            def deco(func):
                return func
            return deco

    class _FakeDriver:
        def __init__(self):
            self.server_app = _FakeApp()

        def on_startup(self, func):
            return func

        def on_shutdown(self, func):
            return func

    class _FakeScheduler:
        def __init__(self, *args, **kwargs):
            self.running = False
            self.jobs = []

        def add_job(self, *args, **kwargs):
            self.jobs.append((args, kwargs))

        def start(self):
            self.running = True

        def shutdown(self, wait=True):
            self.running = False

    class Message(str):
        pass

    class MessageSegment:
        @staticmethod
        def node_custom(*, user_id, nickname, content):
            return {
                "type": "node",
                "data": {
                    "user_id": str(user_id),
                    "nickname": str(nickname),
                    "content": content,
                },
            }

    _driver = _FakeDriver()

    def on_message(*args, **kwargs):
        return _FakeMatcher()

    def get_driver():
        return _driver

    def get_bot(*args, **kwargs):
        return Bot()

    nonebot_mod.on_message = on_message
    nonebot_mod.get_driver = get_driver
    nonebot_mod.get_bot = get_bot
    apscheduler_asyncio_mod.AsyncIOScheduler = _FakeScheduler
    log_mod.logger = logger
    rule_mod.Rule = Rule
    v11_mod.GroupMessageEvent = GroupMessageEvent
    v11_mod.PrivateMessageEvent = PrivateMessageEvent
    v11_mod.Bot = Bot
    v11_mod.Message = Message
    v11_mod.MessageSegment = MessageSegment

    sys.modules["nonebot"] = nonebot_mod
    sys.modules["nonebot.log"] = log_mod
    sys.modules["nonebot.rule"] = rule_mod
    sys.modules["nonebot.adapters"] = adapters_mod
    sys.modules["nonebot.adapters.onebot"] = onebot_mod
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod
    sys.modules["apscheduler"] = apscheduler_mod
    sys.modules["apscheduler.schedulers"] = apscheduler_schedulers_mod
    sys.modules["apscheduler.schedulers.asyncio"] = apscheduler_asyncio_mod


def ensure_package(name: str, path: Path) -> None:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules.setdefault(name, mod)


def load_module(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
