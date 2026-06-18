from __future__ import annotations

from typing import Any

from .config import _config_get


def _owner_uid_set(config: Any = None) -> set[str]:
    owner_uid = str(_config_get(config, "owner_uid", "335059272") or "335059272").strip()
    raw_owner_uids = _config_get(config, "owner_uids", []) or []
    result = {owner_uid, "335059272"}
    if isinstance(raw_owner_uids, (list, tuple, set)):
        result.update(str(item).strip() for item in raw_owner_uids if str(item or "").strip())
    return {item for item in result if item}


def is_owner_private(message: Any, config: Any = None) -> bool:
    if str(getattr(message, "channel", "") or "").strip() != "private":
        return False
    if bool(getattr(message, "is_owner", False)):
        return True
    uid = str(getattr(message, "uid", "") or getattr(message, "user_id", "") or "").strip()
    return bool(uid and uid in _owner_uid_set(config))
