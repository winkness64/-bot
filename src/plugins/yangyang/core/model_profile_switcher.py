from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DEFAULT_ACTIVE_PROFILE_ID = "v4_flash"
SWITCHER_ROOT = "model_profile_switcher"
ACTIVE_PRIVATE_KEY = f"{SWITCHER_ROOT}.active_profile_private"
ACTIVE_GROUP_KEY = f"{SWITCHER_ROOT}.active_profile_group"
VALID_PROFILE_SCOPES: frozenset[str] = frozenset({"private", "group", "current"})
TARGET_PROFILE_SCOPES: frozenset[str] = frozenset({"private", "group"})

# Built-in catalog mirrors ModelRouter.TIERS without importing ModelRouter and
# creating a cycle. Runtime config may add custom profiles under providers.* or
# models.*; those are merged at read time.
BUILTIN_PROFILE_CATALOG: dict[str, dict[str, Any]] = {
    "v4_flash": {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "timeout": 30,
        "cooldown_on_fail": 60,
        "description": "日常水群 / 简单回复",
        "enabled": True,
    },
    "v4_pro": {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "timeout": 60,
        "cooldown_on_fail": 120,
        "description": "架构分析 / 长文报告",
        "enabled": False,
    },
    "gpt_5_4": {
        "provider": "openai_compat",
        "model": "gpt-5.4",
        "timeout": 120,
        "cooldown_on_fail": 300,
        "description": "GPT 5.4 / 代码生成 / 复杂开发",
        "enabled": False,
    },
    "gpt_5_5": {
        "provider": "openai_compat",
        "model": "gpt-5.5",
        "timeout": 120,
        "cooldown_on_fail": 300,
        "description": "GPT 5.5 / 代码生成 / 复杂开发",
        "enabled": False,
    },
    "m2_7": {
        "provider": "openai_compat",
        "model": "MiniMax-M2.7",
        "timeout": 60,
        "cooldown_on_fail": 120,
        "description": "MiniMax M2.7 / 群聊与低风险氛围",
        "enabled": False,
    },
    "minimax_m2_her": {
        "provider": "openai_compat",
        "model": "MiniMax-M2-her",
        "timeout": 120,
        "cooldown_on_fail": 300,
        "description": "MiniMax M2-her / 撒娇调戏玩具",
        "enabled": True,
    },
    "gemini_3_1_pro_high": {
        "provider": "openai_compat",
        "model": "gemini-3.1-pro-high",
        "timeout": 120,
        "cooldown_on_fail": 300,
        "description": "Gemini 3.1 Pro High / 情绪价值与低风险测试",
        "enabled": False,
    },
    "minimax_m3": {
        "provider": "openai_compat",
        "model": "MiniMax-M3",
        "timeout": 120,
        "cooldown_on_fail": 300,
        "description": "MiniMax M3 / 低价工程助理",
        "enabled": False,
    },
}

SENSITIVE_PROFILE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "api-key",
        "api_key_env",
        "authorization",
        "base_url",
        "base-url",
        "endpoint",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "password",
    }
)


def config_get(config: Any, path: str, default: Any = None) -> Any:
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            value = getter(path, default)
            return default if value is None else value
        except TypeError:
            pass
        except Exception:
            return default
    if isinstance(config, Mapping):
        cur: Any = config
    else:
        cur = getattr(config, "data", None)
        if not isinstance(cur, Mapping):
            cur = getattr(config, "overrides", None)
    if isinstance(cur, Mapping):
        for part in path.split("."):
            if not isinstance(cur, Mapping) or part not in cur:
                return default
            cur = cur[part]
        return cur
    return default


def config_set(config: Any, path: str, value: Any) -> bool:
    setter = getattr(config, "set", None)
    if callable(setter):
        try:
            return bool(setter(path, value))
        except TypeError:
            pass
        except Exception:
            return False

    if isinstance(config, Mapping):
        target: Any = config
    else:
        target = getattr(config, "data", None)
        if not isinstance(target, Mapping):
            target = getattr(config, "overrides", None)
    if not isinstance(target, dict):
        return False

    try:
        cur: Any = target
        parts = path.split(".")
        for part in parts[:-1]:
            if not isinstance(cur.get(part), dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value
        return True
    except Exception:
        return False


def channel_from_context(*, channel: Any = None, message: Any = None, session_id: str | None = None) -> str:
    if message is not None:
        raw = str(getattr(message, "channel", "") or "").strip().lower()
        if raw:
            return raw
    raw_channel = str(channel or "").strip().lower()
    if raw_channel:
        return raw_channel
    raw_session = str(session_id or "").strip().lower()
    if raw_session.startswith("private:"):
        return "private"
    if raw_session.startswith("group:"):
        return "group"
    return ""


def resolve_profile_scope(scope: Any = "current", *, context_channel: str | None = None) -> tuple[bool, str, str]:
    raw = str(scope or "current").strip().lower()
    aliases = {
        "私聊": "private",
        "private_chat": "private",
        "dm": "private",
        "群聊": "group",
        "group_chat": "group",
        "当前": "current",
        "当前会话": "current",
    }
    raw = aliases.get(raw, raw)
    if raw not in VALID_PROFILE_SCOPES:
        return False, "", "unsupported_scope"
    if raw == "current":
        channel = str(context_channel or "").strip().lower()
        return True, "group" if channel == "group" else "private", "ok"
    return True, raw, "ok"


def active_profile_path(scope: str) -> str:
    return ACTIVE_GROUP_KEY if scope == "group" else ACTIVE_PRIVATE_KEY


def get_active_profile_id(config: Any, scope: Any = "current", *, context_channel: str | None = None) -> str:
    ok, resolved_scope, _reason = resolve_profile_scope(scope, context_channel=context_channel)
    if not ok:
        resolved_scope = "private"
    return str(config_get(config, active_profile_path(resolved_scope), DEFAULT_ACTIVE_PROFILE_ID) or DEFAULT_ACTIVE_PROFILE_ID).strip() or DEFAULT_ACTIVE_PROFILE_ID


def get_private_active_profile_id(config: Any) -> str:
    return get_active_profile_id(config, "private")


def get_group_active_profile_id(config: Any) -> str:
    return get_active_profile_id(config, "group")


def _mapping_at(config: Any, path: str) -> Mapping[str, Any]:
    value = config_get(config, path, {})
    return value if isinstance(value, Mapping) else {}


def _append_profile_id(ids: list[str], profile_id: Any) -> None:
    pid = str(profile_id or "").strip()
    if pid and pid not in ids:
        ids.append(pid)


def iter_profile_ids(config: Any) -> list[str]:
    """Return stable profile ids for public list/selection.

    Runtime ``providers`` is the primary registry and keeps dict insertion order.
    Built-in and models-only entries are appended as fallback without overriding
    provider-defined ids.
    """
    ids: list[str] = []
    for profile_id, raw in _mapping_at(config, "providers").items():
        if isinstance(raw, Mapping):
            _append_profile_id(ids, profile_id)
    for profile_id in BUILTIN_PROFILE_CATALOG:
        _append_profile_id(ids, profile_id)
    for profile_id, raw in _mapping_at(config, "models").items():
        if isinstance(raw, Mapping):
            _append_profile_id(ids, profile_id)
    return ids


def _profile_source(config: Any, profile_id: str) -> str:
    provider_raw = _mapping_at(config, "providers").get(profile_id)
    if isinstance(provider_raw, Mapping):
        return "providers"
    if profile_id in BUILTIN_PROFILE_CATALOG:
        return "builtin_catalog"
    model_raw = _mapping_at(config, "models").get(profile_id)
    if isinstance(model_raw, Mapping):
        return "models"
    return "missing"


def _profile_index(config: Any, profile_id: str) -> int | None:
    for index, pid in enumerate(iter_profile_ids(config)):
        if pid == profile_id:
            return index
    return None


def profile_exists(config: Any, profile_id: Any) -> bool:
    pid = str(profile_id or "").strip()
    if not pid:
        return False
    if pid in BUILTIN_PROFILE_CATALOG:
        return True
    return isinstance(_mapping_at(config, "providers").get(pid), Mapping) or isinstance(_mapping_at(config, "models").get(pid), Mapping)


def _raw_profile_section(config: Any, section: str, profile_id: str) -> Mapping[str, Any]:
    value = config_get(config, f"{section}.{profile_id}", {})
    return value if isinstance(value, Mapping) else {}


def profile_enabled(config: Any, profile_id: Any) -> bool:
    pid = str(profile_id or "").strip()
    if not pid or not profile_exists(config, pid):
        return False
    provider_cfg = _raw_profile_section(config, "providers", pid)
    model_cfg = _raw_profile_section(config, "models", pid)
    # The profile switcher treats providers.<id>.enabled as the authoritative
    # runtime switch. models.<id>.enabled is only a fallback for models-only
    # entries, so stale model flags cannot hide an enabled provider profile.
    if "enabled" in provider_cfg:
        return bool(provider_cfg.get("enabled"))
    if "enabled" in model_cfg:
        return bool(model_cfg.get("enabled"))
    return bool(BUILTIN_PROFILE_CATALOG.get(pid, {}).get("enabled", False))


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def get_model_profile_descriptor(config: Any, profile_id: Any) -> dict[str, Any]:
    pid = str(profile_id or "").strip()
    builtin = BUILTIN_PROFILE_CATALOG.get(pid, {})
    model_cfg = _raw_profile_section(config, "models", pid)
    provider_cfg = _raw_profile_section(config, "providers", pid)

    provider = str(provider_cfg.get("provider") or builtin.get("provider") or "deepseek")
    model = str(provider_cfg.get("model") or model_cfg.get("model") or builtin.get("model") or pid)
    timeout = _safe_int(provider_cfg.get("timeout", builtin.get("timeout", 30)), 30)
    cooldown = _safe_int(provider_cfg.get("cooldown_on_fail", builtin.get("cooldown_on_fail", 60)), 60)
    description = str(provider_cfg.get("description") or model_cfg.get("description") or builtin.get("description") or "")

    # Deliberately do not copy arbitrary provider/model config. Secrets,
    # base_url/token/env-key names stay out of every public/tool response.
    return {
        "index": _profile_index(config, pid),
        "profile_id": pid,
        "exists": profile_exists(config, pid),
        "enabled": profile_enabled(config, pid),
        "provider": provider,
        "model": model,
        "timeout": timeout,
        "cooldown_on_fail": cooldown,
        "description": description,
        "source": _profile_source(config, pid),
    }


def validate_model_profile_enabled(config: Any, profile_id: Any) -> tuple[bool, str, dict[str, Any]]:
    pid = str(profile_id or "").strip()
    if not pid:
        return False, "missing_profile_id", {}
    if not profile_exists(config, pid):
        return False, "profile_not_found", {"profile_id": pid, "exists": False, "enabled": False}
    descriptor = get_model_profile_descriptor(config, pid)
    if not bool(descriptor.get("enabled")):
        return False, "profile_disabled", descriptor
    return True, "ok", descriptor


def list_model_profiles(
    config: Any,
    *,
    scope: Any = "current",
    include_disabled: bool = False,
    context_channel: str | None = None,
) -> dict[str, Any]:
    ok, resolved_scope, reason = resolve_profile_scope(scope, context_channel=context_channel)
    if not ok:
        resolved_scope = "private"
    private_active = get_private_active_profile_id(config)
    group_active = get_group_active_profile_id(config)
    current_active = private_active if resolved_scope == "private" else group_active
    profiles: list[dict[str, Any]] = []
    for profile_id in iter_profile_ids(config):
        descriptor = get_model_profile_descriptor(config, profile_id)
        if not include_disabled and not bool(descriptor.get("enabled")):
            continue
        item = dict(descriptor)
        item["private_active"] = profile_id == private_active
        item["group_active"] = profile_id == group_active
        item["current_active"] = profile_id == current_active
        profiles.append(item)
    return {
        "ok": ok,
        "reason": reason,
        "scope": resolved_scope,
        "current_scope": resolved_scope,
        "private_active": private_active,
        "group_active": group_active,
        "current_active": current_active,
        "profiles": profiles,
    }


def get_active_model_profile(
    config: Any,
    *,
    scope: Any = "current",
    context_channel: str | None = None,
) -> dict[str, Any]:
    ok, resolved_scope, reason = resolve_profile_scope(scope, context_channel=context_channel)
    if not ok:
        resolved_scope = "private"
    private_active = get_private_active_profile_id(config)
    group_active = get_group_active_profile_id(config)
    active = private_active if resolved_scope == "private" else group_active
    descriptor = get_model_profile_descriptor(config, active)
    return {
        "ok": ok,
        "reason": reason,
        "scope": resolved_scope,
        "current_scope": resolved_scope,
        "profile_id": active,
        "profile": descriptor,
        "private_active": private_active,
        "group_active": group_active,
    }


def _selection_index_to_profile_id(config: Any, selection_index: Any) -> tuple[bool, str, str]:
    if isinstance(selection_index, bool):
        return False, "", "invalid_selection_index"
    try:
        if isinstance(selection_index, str):
            raw = selection_index.strip()
            if not raw or not raw.lstrip("+-").isdigit():
                return False, "", "invalid_selection_index"
            index = int(raw)
        else:
            index = int(selection_index)
    except Exception:
        return False, "", "invalid_selection_index"
    profile_ids = iter_profile_ids(config)
    if index < 0 or index >= len(profile_ids):
        return False, "", "invalid_selection_index"
    return True, profile_ids[index], "ok"


def set_active_model_profile(
    config: Any,
    *,
    profile_id: Any = None,
    selection_index: Any = None,
    scope: Any = "current",
    context_channel: str | None = None,
) -> dict[str, Any]:
    ok_scope, resolved_scope, scope_reason = resolve_profile_scope(scope, context_channel=context_channel)
    before_private = get_private_active_profile_id(config)
    before_group = get_group_active_profile_id(config)
    if not ok_scope:
        return {
            "ok": False,
            "reason": scope_reason,
            "scope": str(scope or ""),
            "previous": None,
            "current": None,
            "private_active": before_private,
            "group_active": before_group,
        }

    if selection_index is not None:
        ok_index, indexed_profile_id, index_reason = _selection_index_to_profile_id(config, selection_index)
        if not ok_index:
            return {
                "ok": False,
                "reason": index_reason,
                "scope": resolved_scope,
                "selection_index": selection_index,
                "profile_id": str(profile_id or "").strip(),
                "previous": before_private if resolved_scope == "private" else before_group,
                "current": before_private if resolved_scope == "private" else before_group,
                "private_active": before_private,
                "group_active": before_group,
            }
        profile_id = indexed_profile_id
        resolved_from_index = True

    pid = str(profile_id or "").strip()
    ok_profile, profile_reason, descriptor = validate_model_profile_enabled(config, pid)
    if not ok_profile:
        return {
            "ok": False,
            "reason": profile_reason,
            "scope": resolved_scope,
            "profile_id": pid,
            "selection_index": selection_index if selection_index is not None else descriptor.get("index"),
            "previous": before_private if resolved_scope == "private" else before_group,
            "current": before_private if resolved_scope == "private" else before_group,
            "private_active": before_private,
            "group_active": before_group,
            "profile": descriptor,
        }

    previous = before_private if resolved_scope == "private" else before_group
    write_ok = config_set(config, active_profile_path(resolved_scope), pid)
    after_private = get_private_active_profile_id(config)
    after_group = get_group_active_profile_id(config)
    if not write_ok:
        return {
            "ok": False,
            "reason": "config_write_failed",
            "scope": resolved_scope,
            "profile_id": pid,
            "selection_index": selection_index if selection_index is not None else descriptor.get("index"),
            "previous": previous,
            "current": previous,
            "private_active": before_private,
            "group_active": before_group,
            "profile": descriptor,
        }
    return {
        "ok": True,
        "reason": "ok",
        "scope": resolved_scope,
        "profile_id": pid,
        "previous": previous,
        "current": pid,
        "private_active": after_private,
        "group_active": after_group,
        "profile": descriptor,
    }


def set_model_profile_enabled(
    config: Any,
    *,
    profile_id: Any = None,
    selection_index: Any = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Enable or disable exactly one model profile without switching active scope."""
    if selection_index is not None:
        ok_index, indexed_profile_id, index_reason = _selection_index_to_profile_id(config, selection_index)
        if not ok_index:
            return {
                "ok": False,
                "reason": index_reason,
                "profile_id": str(profile_id or "").strip(),
                "selection_index": selection_index,
                "enabled": None,
            }
        profile_id = indexed_profile_id

    pid = str(profile_id or "").strip()
    if not pid:
        return {"ok": False, "reason": "missing_profile_id", "profile_id": pid, "selection_index": selection_index, "enabled": None}
    if not profile_exists(config, pid):
        return {"ok": False, "reason": "profile_not_found", "profile_id": pid, "selection_index": selection_index, "enabled": None}

    before = get_model_profile_descriptor(config, pid)
    desired = bool(enabled)
    provider_cfg = dict(_raw_profile_section(config, "providers", pid))
    model_cfg = dict(_raw_profile_section(config, "models", pid))
    provider_cfg["enabled"] = desired
    model_cfg["enabled"] = desired
    if "model" not in model_cfg:
        model_cfg["model"] = before.get("model") or pid
    ok_provider = config_set(config, f"providers.{pid}", provider_cfg)
    ok_model = config_set(config, f"models.{pid}", model_cfg)
    after = get_model_profile_descriptor(config, pid)
    if not (ok_provider and ok_model):
        return {
            "ok": False,
            "reason": "config_write_failed",
            "profile_id": pid,
            "selection_index": selection_index if selection_index is not None else before.get("index"),
            "previous_enabled": before.get("enabled"),
            "enabled": before.get("enabled"),
            "profile": before,
        }
    return {
        "ok": True,
        "reason": "ok",
        "profile_id": pid,
        "selection_index": selection_index if selection_index is not None else after.get("index"),
        "previous_enabled": before.get("enabled"),
        "enabled": after.get("enabled"),
        "profile": after,
    }


def _sanitize_profile_id_part(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    chars: list[str] = []
    prev_us = False
    for ch in lowered:
        if ch.isalnum():
            chars.append(ch)
            prev_us = False
        else:
            if not prev_us:
                chars.append("_")
                prev_us = True
    return "".join(chars).strip("_")


def _profile_id_from_model_id(model_id: Any, *, prefix: Any = "") -> str:
    base = _sanitize_profile_id_part(model_id)
    if not base:
        return ""
    clean_prefix = _sanitize_profile_id_part(prefix)
    if clean_prefix and not base.startswith(f"{clean_prefix}_"):
        base = f"{clean_prefix}_{base}"
    return base[:80]


def refresh_model_profiles_from_models(
    config: Any,
    *,
    provider_profile_id: Any,
    model_ids: list[Any],
    enable_discovered: bool = False,
    timeout: Any = None,
    cooldown_on_fail: Any = None,
    description_prefix: str = "discovered via /models",
) -> dict[str, Any]:
    """Merge provider /models result into runtime_config providers/models.

    This writes only non-sensitive profile metadata.  It intentionally does not
    copy or expose api_key/base_url/token values.  New profiles default disabled
    unless enable_discovered=True is explicitly supplied by owner/tool caller.
    """
    source_pid = str(provider_profile_id or "").strip()
    if not source_pid:
        return {"ok": False, "reason": "missing_provider_profile_id", "provider_profile_id": source_pid}
    source = get_model_profile_descriptor(config, source_pid)
    if not bool(source.get("exists")):
        return {"ok": False, "reason": "provider_profile_not_found", "provider_profile_id": source_pid}
    provider_name = str(source.get("provider") or "").strip()
    if provider_name != "openai_compat":
        return {"ok": False, "reason": "unsupported_provider", "provider_profile_id": source_pid, "provider": provider_name}

    clean_model_ids: list[str] = []
    for item in model_ids or []:
        mid = str(item or "").strip()
        if mid and mid not in clean_model_ids:
            clean_model_ids.append(mid)
    if not clean_model_ids:
        return {"ok": False, "reason": "empty_model_list", "provider_profile_id": source_pid}

    source_provider_cfg = dict(_raw_profile_section(config, "providers", source_pid))
    source_model_cfg = dict(_raw_profile_section(config, "models", source_pid))
    family = str(source_provider_cfg.get("family") or source_model_cfg.get("family") or source_pid).strip() or source_pid
    profile_prefix = str(source_provider_cfg.get("profile_prefix") or source_model_cfg.get("profile_prefix") or "").strip()
    base_timeout = _safe_int(timeout if timeout is not None else source_provider_cfg.get("timeout", source.get("timeout", 60)), 60)
    base_cooldown = _safe_int(cooldown_on_fail if cooldown_on_fail is not None else source_provider_cfg.get("cooldown_on_fail", source.get("cooldown_on_fail", 120)), 120)
    api_key_env = source_provider_cfg.get("api_key_env")
    base_url_env = source_provider_cfg.get("base_url_env")

    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for model_id in clean_model_ids:
        generated_id = _profile_id_from_model_id(model_id, prefix=profile_prefix)
        if not generated_id:
            skipped.append({"model": model_id, "reason": "bad_model_id"})
            continue
        profile_id = generated_id
        if profile_exists(config, profile_id) and profile_id != source_pid:
            # Built-in/placeholders are meant to be refreshed from /models.  For
            # truly custom existing profiles, avoid overwriting an unrelated
            # hand-written profile when the generated id collides.
            existing = get_model_profile_descriptor(config, profile_id)
            if profile_id not in BUILTIN_PROFILE_CATALOG and str(existing.get("model") or "") != model_id:
                skipped.append({"model": model_id, "profile_id": profile_id, "reason": "profile_id_conflict"})
                continue
        provider_payload: dict[str, Any] = {
            "provider": "openai_compat",
            "model": model_id,
            "timeout": base_timeout,
            "cooldown_on_fail": base_cooldown,
            "enabled": bool(enable_discovered) if not profile_exists(config, profile_id) else profile_enabled(config, profile_id),
            "description": f"{description_prefix}: {model_id}",
            "discovered_from": source_pid,
            "family": family,
            "profile_prefix": profile_prefix,
        }
        if api_key_env:
            provider_payload["api_key_env"] = str(api_key_env)
        if base_url_env:
            provider_payload["base_url_env"] = str(base_url_env)
        model_payload: dict[str, Any] = {
            "model": model_id,
            "enabled": bool(enable_discovered) if not profile_exists(config, profile_id) else profile_enabled(config, profile_id),
            "description": f"{description_prefix}: {model_id}",
            "discovered_from": source_pid,
            "family": family,
            "profile_prefix": profile_prefix,
        }

        was_existing = profile_exists(config, profile_id)
        ok_provider = config_set(config, f"providers.{profile_id}", provider_payload)
        ok_model = config_set(config, f"models.{profile_id}", model_payload)
        if not (ok_provider and ok_model):
            return {"ok": False, "reason": "config_write_failed", "profile_id": profile_id, "provider_profile_id": source_pid}
        item = {"profile_id": profile_id, "model": model_id, "enabled": bool(provider_payload.get("enabled"))}
        (updated if was_existing else created).append(item)

    return {
        "ok": True,
        "reason": "ok",
        "provider_profile_id": source_pid,
        "provider": provider_name,
        "models_seen": len(clean_model_ids),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "enable_discovered": bool(enable_discovered),
        "profile_prefix": profile_prefix,
    }


def choose_profile_for_channel(
    config: Any,
    requested_tier: Any = None,
    *,
    channel: Any = None,
    message: Any = None,
    session_id: str | None = None,
) -> tuple[str, str]:
    """Resolve a call profile from channel/session context.

    Returns (profile_id, resolved_channel). Unknown channel intentionally keeps
    legacy requested_tier/ORDER behavior; private/group use their independent
    active profile if it is valid and enabled.
    """
    resolved_channel = channel_from_context(channel=channel, message=message, session_id=session_id)
    requested = str(requested_tier or DEFAULT_ACTIVE_PROFILE_ID).strip() or DEFAULT_ACTIVE_PROFILE_ID
    if resolved_channel in {"private", "group"}:
        active = get_active_profile_id(config, resolved_channel)
        if profile_enabled(config, active):
            return active, resolved_channel
        return DEFAULT_ACTIVE_PROFILE_ID, resolved_channel
    return requested, resolved_channel
