from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from nonebot.log import logger

from .event_adapter import Message


@dataclass
class Decision:
    should_reply: bool
    reply_style: str
    model_tier: str | None
    reply_budget: int
    target_uid: Optional[str] = None
    reason: str = ""
    is_forced: bool = False


class DecisionEngine:
    """第一阶段群聊裁判：只做硬规则，不调 LLM。"""

    def __init__(self, store=None, skill_loader=None):
        self.store = store
        self.skill_loader = skill_loader

    def decide(self, msg: Message) -> Decision:
        try:
            if not msg.text and not msg.images:
                return Decision(False, "silent", None, 0, None, "empty_message", False)

            # 私聊：直接回应漂♂总/用户。
            if msg.channel == "private":
                return Decision(
                    should_reply=True,
                    reply_style="warm",
                    model_tier="v4_flash",
                    reply_budget=3,
                    target_uid=msg.uid,
                    reason="private_message",
                    is_forced=True,
                )

            # owner / 漂♂总明确指令优先级最高，不受 quote 规则与普通静默影响。
            if msg.owner_command or msg.explicit_command:
                return Decision(
                    should_reply=True,
                    reply_style="warm",
                    model_tier="v4_flash",
                    reply_budget=2,
                    target_uid=msg.uid,
                    reason="owner_explicit_command",
                    is_forced=True,
                )

            # owner 群聊 @bot：强制放行。
            if msg.is_owner and msg.is_at_bot:
                return Decision(
                    should_reply=True,
                    reply_style="warm",
                    model_tier="v4_flash",
                    reply_budget=2,
                    target_uid=msg.uid,
                    reason="owner_at_bot",
                    is_forced=True,
                )

            # 群聊 quote/reply 规则：
            # - 单独引用 bot 上一条消息，不构成回复资格
            # - 引用 bot 仍需同时 @bot，才允许回复
            # - 引用普通人且不 @bot，也默认静默
            if msg.is_reply_to_bot and not msg.is_at_bot:
                return Decision(False, "silent", None, 0, None, "reply_to_bot_without_at", False)

            # 群聊明确 @ bot：允许回复。
            if msg.is_at_bot:
                return Decision(
                    should_reply=True,
                    reply_style="warm",
                    model_tier="v4_flash",
                    reply_budget=2,
                    target_uid=msg.uid,
                    reason="at_bot",
                    is_forced=True,
                )

            # 其它群聊默认静默。
            return Decision(False, "silent", None, 0, None, "default_silent", False)
        except Exception:
            logger.exception("DecisionEngine: failed to decide")
            return Decision(False, "silent", None, 0, None, "exception", False)
