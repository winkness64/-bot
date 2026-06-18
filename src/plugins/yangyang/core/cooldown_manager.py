from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from nonebot.log import logger


@dataclass
class CooldownState:
    """MVP 冷却状态，进程内保存即可。"""

    global_last_reply: float = 0.0
    topic_last_reply: dict[str, float] = field(default_factory=dict)
    topic_round_count: dict[str, int] = field(default_factory=dict)
    daily_count: int = 0
    daily_reset_at: date | None = None
    group_bot_loop_cooldown_until: dict[str, float] = field(default_factory=dict)


class CooldownManager:
    """全局冷却、同话题冷却、每日主动上限与群级 bot loop 冷却。"""

    def __init__(self, cfg: Any):
        self.cfg = cfg
        self.state = CooldownState()

    def _get_cfg(self, key: str, default: Any) -> Any:
        """兼容 RuntimeConfig.get('behavior.xxx', default)。"""
        try:
            if self.cfg is None:
                return default
            if hasattr(self.cfg, "get"):
                value = self.cfg.get(key, default)
                return default if value is None else value
            return default
        except Exception:
            logger.exception("CooldownManager: failed to read config: %s", key)
            return default

    def _reset_daily_if_needed(self) -> None:
        """按自然日重置每日主动回复计数。"""
        try:
            today = date.today()
            if self.state.daily_reset_at != today:
                self.state.daily_count = 0
                self.state.daily_reset_at = today
        except Exception:
            logger.exception("CooldownManager: failed to reset daily counter")

    def can_reply(self, group_id: str, topic_hint: str, is_forced: bool) -> bool:
        """
        判断当前是否允许回复。

        is_forced=True 通常代表被 @ 或阿漂强制指令，直接跳过冷却与主动上限。
        """
        try:
            if is_forced:
                return True

            now = time.time()

            # 1. 全局冷却：防止连续冒泡。
            cooldown_global_s = float(self._get_cfg("behavior.cooldown_global_s", 60))
            if cooldown_global_s > 0 and now - self.state.global_last_reply < cooldown_global_s:
                return False

            # 2. 同话题冷却：只有 topic_hint 非空才启用，避免空 topic 退化成全局话题冷却。
            if topic_hint:
                topic_key = f"{group_id}:{topic_hint}"
                topic_rounds = self.state.topic_round_count.get(topic_key, 0)
                topic_last = self.state.topic_last_reply.get(topic_key, 0.0)
                max_rounds = int(self._get_cfg("behavior.cooldown_topic_rounds", 3))
                cooldown_topic_s = float(self._get_cfg("behavior.cooldown_topic_s", 300))

                # 设计目标：同话题可聊 max_rounds 轮，达到上限后静默 cooldown_topic_s。
                if max_rounds > 0 and topic_rounds >= max_rounds:
                    if cooldown_topic_s <= 0 or now - topic_last >= cooldown_topic_s:
                        # 冷却已过，放行并重置该话题轮次，从新一轮开始。
                        self.state.topic_round_count[topic_key] = 0
                    else:
                        return False

            # 3. 每日主动回复上限：forced 不计入，这里只检查非 forced。
            self._reset_daily_if_needed()
            daily_limit = int(self._get_cfg("behavior.daily_auto_reply_limit", 15))
            if daily_limit > 0 and self.state.daily_count >= daily_limit:
                return False

            return True
        except Exception:
            logger.exception("CooldownManager: failed to check can_reply")
            return False

    def record_reply(self, group_id: str, topic_hint: str, is_forced: bool = False) -> None:
        """记录一次实际发送的回复。"""
        try:
            now = time.time()
            self.state.global_last_reply = now

            if topic_hint:
                topic_key = f"{group_id}:{topic_hint}"
                self.state.topic_last_reply[topic_key] = now
                self.state.topic_round_count[topic_key] = self.state.topic_round_count.get(topic_key, 0) + 1

            self._reset_daily_if_needed()
            if not is_forced:
                self.state.daily_count += 1
        except Exception:
            logger.exception("CooldownManager: failed to record reply")

    def is_group_bot_loop_cooling(self, group_id: str) -> bool:
        """指定群是否处于 bot loop 冷却中。"""
        try:
            if not group_id:
                return False
            now = time.time()
            return now < float(self.state.group_bot_loop_cooldown_until.get(str(group_id), 0.0))
        except Exception:
            logger.exception("CooldownManager: failed to check group bot loop cooling")
            return False

    def activate_group_bot_loop_cooldown(self, group_id: str, seconds: float | None = None) -> None:
        """为指定群设置 bot loop 冷却。"""
        try:
            if not group_id:
                return
            cooldown_s = float(
                seconds
                if seconds is not None
                else self._get_cfg("behavior.bot_loop_cooldown_seconds", 300)
            )
            self.state.group_bot_loop_cooldown_until[str(group_id)] = time.time() + max(cooldown_s, 0.0)
        except Exception:
            logger.exception("CooldownManager: failed to activate group bot loop cooldown")
