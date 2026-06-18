from __future__ import annotations

from typing import Any
import importlib
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from nonebot.log import logger

try:
    from nonebot import get_driver, get_bot
except ImportError:  # pragma: no cover - test fallback
    get_driver = None
    get_bot = None

from ..memory.pipeline import MemoryPipeline
from ..core.token_usage import format_token_usage_push_summary, summarize_token_usage


DEFAULT_PIPELINE_INTERVAL_MINUTES = 30
_scheduler: AsyncIOScheduler | None = None
_pipeline: MemoryPipeline | None = None
_driver_hooks_registered = False


def _get_plugin_module():
    """获取当前包所属的 yangyang 插件模块，避免 plugins/src.plugins 双路径重复导入。"""
    package_name = str(__package__ or "")
    parent_name = package_name.rsplit(".", 1)[0] if "." in package_name else "plugins.yangyang"
    module = sys.modules.get(parent_name)
    if module is not None:
        return module
    try:
        return importlib.import_module(parent_name)
    except ImportError:
        logger.warning(f"Tasks: {parent_name} not importable yet")
        return None


def _get_store():
    """从当前插件模块获取 MemoryStore 实例。"""
    module = _get_plugin_module()
    return getattr(module, "store", None) if module is not None else None


def _get_runtime_config():
    module = _get_plugin_module()
    return getattr(module, "cfg", None) if module is not None else None


def _get_or_create_pipeline() -> MemoryPipeline | None:
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    store = _get_store()
    if store is None:
        return None
    _pipeline = MemoryPipeline(store)
    return _pipeline


def resolve_pipeline_interval_minutes(config: Any = None, default: int = DEFAULT_PIPELINE_INTERVAL_MINUTES) -> int:
    runtime_config = config if config is not None else _get_runtime_config()
    raw_value = default
    if runtime_config is not None:
        try:
            raw_value = runtime_config.get("memory_pipeline_interval_minutes", default)
        except Exception:
            logger.exception("Tasks: failed to read memory_pipeline_interval_minutes")
            raw_value = default
    try:
        interval = int(default if raw_value is None else raw_value)
    except (TypeError, ValueError):
        interval = default
    return max(1, interval)


async def run_candidate_pipeline() -> None:
    """定时任务：执行一轮候选提取 + 升格管线。"""
    pipeline = _get_or_create_pipeline()
    if pipeline is None:
        logger.warning("Tasks: MemoryPipeline skipped — store not available")
        return
    try:
        stats = pipeline.run_once()
        logger.info(
            f"Tasks: pipeline completed — sessions={stats.get('sessions_scanned', 0)} "
            f"msgs={stats.get('messages_collected', 0)} raw_candidates={stats.get('new_candidates', 0)} "
            f"aggregated_candidates={stats.get('candidates_after_dedup', 0)} promoted={stats.get('promoted', 0)} "
            f"errors={stats.get('errors', 0)}"
        )
    except Exception:
        logger.exception("Tasks: pipeline run failed")


async def run_token_usage_hourly_push() -> None:
    """每小时向 owner 私聊推送最近 token 用量。"""
    runtime_config = _get_runtime_config()
    if runtime_config is None:
        return
    try:
        enabled = bool(runtime_config.get_bool("token_usage_hourly_push_enabled", True)) if hasattr(runtime_config, "get_bool") else bool(runtime_config.get("token_usage_hourly_push_enabled", True))
    except Exception:
        enabled = True
    if not enabled:
        return
    owner_uid = ""
    try:
        owner_uid = str(runtime_config.get("owner_uid", "") or "")
    except Exception:
        owner_uid = ""
    if not owner_uid:
        logger.warning("Tasks: token usage push skipped — owner_uid missing")
        return
    try:
        hours = int(runtime_config.get("token_usage_hourly_push_hours", 1) or 1)
    except Exception:
        hours = 1
    safe_hours = max(1, hours)
    summary = summarize_token_usage(runtime_config, hours=safe_hours, group_by="model")
    today_summary = summarize_token_usage(runtime_config, period="today", group_by="model")
    text = format_token_usage_push_summary(summary, hours=safe_hours, today=today_summary, group_by="model")
    if get_bot is None:
        logger.warning("Tasks: token usage push skipped — get_bot unavailable")
        return
    try:
        bot = get_bot()
        await bot.send_private_msg(user_id=int(owner_uid), message=text)
        logger.info("Tasks: token usage hourly pushed owner=%s available=%s total=%s", owner_uid, summary.available, summary.total_tokens)
    except Exception:
        logger.exception("Tasks: token usage hourly push failed")


def start_scheduler(interval_minutes: int | None = None) -> None:
    """启动定时管线。默认按运行时配置读取，缺省每30分钟跑一次。"""
    global _scheduler
    if _scheduler is not None:
        if getattr(_scheduler, "running", False):
            logger.warning("Tasks: scheduler already running")
            return
        _scheduler = None

    resolved_interval = resolve_pipeline_interval_minutes(default=DEFAULT_PIPELINE_INTERVAL_MINUTES) if interval_minutes is None else max(1, int(interval_minutes))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_candidate_pipeline,
        "interval",
        minutes=resolved_interval,
        id="memory_pipeline",
        replace_existing=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        run_token_usage_hourly_push,
        "interval",
        hours=1,
        id="token_usage_hourly_push",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(f"Tasks: scheduler started — interval={resolved_interval} min")


def stop_scheduler() -> None:
    """停止定时管线。"""
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("Tasks: scheduler shutdown error")
    _scheduler = None
    logger.info("Tasks: scheduler stopped")


def register_driver_hooks() -> None:
    global _driver_hooks_registered
    if _driver_hooks_registered:
        return
    if get_driver is None:
        return

    try:
        driver = get_driver()
    except Exception:
        logger.warning("Tasks: nonebot driver unavailable; skip scheduler hook registration")
        return

    @driver.on_startup
    async def _on_startup() -> None:
        start_scheduler()

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        stop_scheduler()

    _driver_hooks_registered = True


register_driver_hooks()
