from __future__ import annotations

import os
import time


class Seg:
    def __init__(self, seg_type: str, **data):
        self.type = seg_type
        self.data = data


class FakeSenderInfo:
    def __init__(self, nickname: str, card: str = ""):
        self.nickname = nickname
        self.card = card


class FakeReplySender:
    def __init__(self, user_id: str):
        self.user_id = user_id


class FakeReply:
    def __init__(self, message_id: str, user_id: str):
        self.message_id = message_id
        self.user_id = user_id
        self.sender = FakeReplySender(user_id)


class FakeEvent:
    def __init__(
        self,
        *,
        self_id: str,
        user_id: str,
        message_id: str,
        message: list[Seg],
        raw_message: str,
        sender: FakeSenderInfo,
        group_id: str | None = None,
        reply: FakeReply | None = None,
        explicit_command: bool | None = None,
        owner_command: bool | None = None,
    ):
        self.self_id = self_id
        self.user_id = user_id
        self.message_id = message_id
        self.message = message
        self.raw_message = raw_message
        self.sender = sender
        self.group_id = group_id
        self.time = int(time.time())
        self.reply = reply
        self.explicit_command = explicit_command
        self.owner_command = owner_command


class DictConfig:
    def __init__(self, data: dict):
        self.data = data

    def get(self, path: str, default=None):
        cur = self.data
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, path: str, value):
        cur = self.data
        parts = path.split(".")
        for part in parts[:-1]:
            if not isinstance(cur.get(part), dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value
        return True

    def get_bool(self, path: str, default: bool = False, env_key: str | None = None):
        if env_key:
            env = os.getenv(env_key)
            if env is not None:
                return str(env).strip().lower() in {"1", "true", "yes", "on"}
        value = self.get(path, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}


class FakeBot:
    def __init__(self, self_id: str = "90001"):
        self.self_id = self_id
        self.group_sent: list[tuple[int, str]] = []
        self.private_sent: list[tuple[int, str]] = []

    async def send_group_msg(self, group_id: int, message: str):
        self.group_sent.append((group_id, message))

    async def send_private_msg(self, user_id: int, message: str):
        self.private_sent.append((user_id, message))
