from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Optional

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from nonebot.log import logger

from .owner_rules import is_explicit_owner_command_text, is_owner_uid


# ── 标准消息模型 ──

@dataclass
class Message:
    """NoneBot 事件归一化后的内部消息。"""

    msg_id: str
    uid: str
    nick: str
    group_id: str
    channel: str
    text: str
    raw_content: str
    is_at_bot: bool
    is_at_owner: bool
    is_quote_bot: bool
    quote_target_msg_id: Optional[str]
    at_user_ids: list[str] = field(default_factory=list)
    bot_self_id: str = ""
    reply_to_message_id: Optional[str] = None
    reply_to_user_id: Optional[str] = None
    is_reply_to_bot: bool = False
    is_owner: bool = False
    owner_command: bool = False
    explicit_command: bool = False
    images: list[str] = field(default_factory=list)
    timestamp: float = 0.0


# ── 事件适配器 ──

class EventAdapter:
    """将 OneBot v11 事件转换为内部 Message。"""

    def __init__(self, owner_id: str = "335059272", owner_uids: list[str] | None = None) -> None:
        self.owner_id = str(owner_id)
        self.owner_uids = [str(uid) for uid in (owner_uids or [self.owner_id]) if str(uid or "")]

    def adapt_group_msg(self, event: GroupMessageEvent) -> Message:
        """适配群聊消息。"""
        return self._adapt(event, channel="group")

    def adapt_private_msg(self, event: PrivateMessageEvent) -> Message:
        """适配私聊消息。"""
        return self._adapt(event, channel="private")

    def _adapt(self, event: GroupMessageEvent | PrivateMessageEvent, channel: str) -> Message:
        """适配通用字段。"""
        try:
            self_id = str(event.self_id)
            uid = str(event.user_id)
            group_id = str(getattr(event, "group_id", "") or "")
            raw_content = getattr(event, "raw_message", "") or str(event.message)
            sender = getattr(event, "sender", None)
            nick = (
                getattr(sender, "card", None)
                or getattr(sender, "nickname", None)
                or uid
            )

            reply_to_message_id, reply_to_user_id, is_reply_to_bot = self._extract_reply_info(event, self_id)
            text = self._clean_text(event)
            is_owner = is_owner_uid(uid, self.owner_uids, self.owner_id)
            owner_command = self._extract_owner_command(event, uid, self_id, text)

            return Message(
                msg_id=str(event.message_id),
                uid=uid,
                nick=str(nick),
                group_id=group_id,
                channel=channel,
                text=text,
                raw_content=str(raw_content),
                is_at_bot=self._extract_at(event, self_id),
                is_at_owner=self._extract_at(event, self.owner_id),
                is_quote_bot=is_reply_to_bot,
                quote_target_msg_id=reply_to_message_id,
                at_user_ids=self._extract_at_user_ids(event),
                bot_self_id=self_id,
                reply_to_message_id=reply_to_message_id,
                reply_to_user_id=reply_to_user_id,
                is_reply_to_bot=is_reply_to_bot,
                is_owner=is_owner,
                owner_command=owner_command,
                explicit_command=owner_command,
                images=self._extract_image_urls(event),
                timestamp=float(getattr(event, "time", 0) or 0),
            )
        except Exception:
            logger.exception("EventAdapter: failed to adapt event")
            return self._fallback_message(event, channel)

    def _fallback_message(self, event: GroupMessageEvent | PrivateMessageEvent, channel: str) -> Message:
        """适配失败时返回最小安全消息，避免主流程崩溃。"""
        uid = str(getattr(event, "user_id", "") or "")
        sender = getattr(event, "sender", None)
        return Message(
            msg_id=str(getattr(event, "message_id", "") or ""),
            uid=uid,
            nick=str(getattr(sender, "nickname", None) or uid),
            group_id=str(getattr(event, "group_id", "") or ""),
            channel=channel,
            text="",
            raw_content=str(getattr(event, "raw_message", "") or ""),
            is_at_bot=False,
            is_at_owner=False,
            is_quote_bot=False,
            quote_target_msg_id=None,
            at_user_ids=[],
            bot_self_id="",
            reply_to_message_id=None,
            reply_to_user_id=None,
            is_reply_to_bot=False,
            is_owner=False,
            owner_command=False,
            explicit_command=False,
            images=[],
            timestamp=float(getattr(event, "time", 0) or 0),
        )

    def _extract_at(self, event: GroupMessageEvent | PrivateMessageEvent, target_uid: str) -> bool:
        """判断消息是否 @ 指定用户。"""
        try:
            for seg in event.message:
                if seg.type != "at":
                    continue
                qq = str(seg.data.get("qq", "") or "").strip()
                if qq == "all":
                    continue
                if qq == str(target_uid):
                    return True
        except Exception:
            logger.exception("EventAdapter: failed to extract at segment")

        raw_message = str(getattr(event, "raw_message", "") or "")
        return str(target_uid) in self._extract_at_user_ids_from_raw(raw_message)

    def _extract_at_user_ids(self, event: GroupMessageEvent | PrivateMessageEvent) -> list[str]:
        """提取消息中真实 @ 的用户列表。"""
        user_ids: list[str] = []
        try:
            for seg in event.message:
                if seg.type != "at":
                    continue
                qq = str(seg.data.get("qq", "") or "").strip()
                if not qq or qq == "all" or qq in user_ids:
                    continue
                user_ids.append(qq)
        except Exception:
            logger.exception("EventAdapter: failed to extract at user ids")

        raw_message = str(getattr(event, "raw_message", "") or "")
        for qq in self._extract_at_user_ids_from_raw(raw_message):
            if qq not in user_ids:
                user_ids.append(qq)
        return user_ids

    def _extract_at_user_ids_from_raw(self, raw_message: str) -> list[str]:
        """从 raw_message 的 CQ 码兜底提取 @ 用户列表。"""
        user_ids: list[str] = []
        try:
            for match in re.finditer(r"\[CQ:at,qq=([^,\]]+)", str(raw_message or "")):
                qq = str(match.group(1) or "").strip()
                if not qq or qq == "all" or qq in user_ids:
                    continue
                user_ids.append(qq)
        except Exception:
            logger.exception("EventAdapter: failed to extract at user ids from raw_message")
        return user_ids

    def _extract_image_urls(self, event: GroupMessageEvent | PrivateMessageEvent) -> list[str]:
        """提取图片 URL 或文件标识。"""
        images: list[str] = []
        try:
            for seg in event.message:
                if seg.type != "image":
                    continue
                url = seg.data.get("url") or seg.data.get("file")
                if url:
                    images.append(str(url))
        except Exception:
            logger.exception("EventAdapter: failed to extract images")
        return images

    def _clean_text(self, event: GroupMessageEvent | PrivateMessageEvent) -> str:
        """仅拼接 text 段，过滤 at/image/reply 等结构段。"""
        parts: list[str] = []
        try:
            for seg in event.message:
                if seg.type == "text":
                    text = seg.data.get("text", "")
                    if text:
                        parts.append(str(text))
        except Exception:
            logger.exception("EventAdapter: failed to clean text")
        return "".join(parts).strip()

    def _extract_reply_info(
        self,
        event: GroupMessageEvent | PrivateMessageEvent,
        self_id: str,
    ) -> tuple[Optional[str], Optional[str], bool]:
        """提取 reply/quote 信息。"""
        try:
            reply = getattr(event, "reply", None)
            if reply is not None:
                target_msg_id = str(getattr(reply, "message_id", "") or "") or None
                sender = getattr(reply, "sender", None)
                reply_uid = getattr(sender, "user_id", None) if sender is not None else None
                if reply_uid is None:
                    reply_uid = getattr(reply, "user_id", None)
                reply_uid = str(reply_uid or "") or None
                return target_msg_id, reply_uid, str(reply_uid or "") == str(self_id)

            for seg in event.message:
                if seg.type != "reply":
                    continue
                target_msg_id = str(seg.data.get("id") or seg.data.get("message_id") or "") or None
                reply_uid = str(seg.data.get("user_id") or seg.data.get("qq") or "") or None
                is_reply_to_bot = str(reply_uid or "") == str(self_id) if reply_uid else False
                return target_msg_id, reply_uid, is_reply_to_bot
        except Exception:
            logger.exception("EventAdapter: failed to extract quote info")
        return None, None, False

    def _extract_owner_command(
        self,
        event: GroupMessageEvent | PrivateMessageEvent,
        uid: str,
        self_id: str,
        text: str,
    ) -> bool:
        """提取 owner 明确指令标记。"""
        try:
            preset = getattr(event, "owner_command", None)
            if preset is None:
                preset = getattr(event, "explicit_command", None)
            if preset is None:
                preset = getattr(event, "is_explicit_command", None)
            if preset is not None:
                return bool(preset) and is_owner_uid(uid, self.owner_uids, self.owner_id)

            if not is_owner_uid(uid, self.owner_uids, self.owner_id):
                return False

            if self._extract_at(event, self_id):
                return True

            return is_explicit_owner_command_text(text)
        except Exception:
            logger.exception("EventAdapter: failed to extract owner command")
            return False
