from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


TOOL_LOOP_MAX_STEPS_CONFIG_KEY = "owner_toolbox_light_native_loop_max_steps"
TOOL_LOOP_MAX_STEPS_ALIAS_KEYS: tuple[str, ...] = (
    "owner_toolbox_tool_loop_max_steps",
    "model_tool_loop_max_steps",
)
TOOL_LOOP_MAX_STEPS_DEFAULT = 5
TOOL_LOOP_MAX_STEPS_MIN = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _config_get(config: Any, path: str, default: Any = None) -> Any:
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            return getter(path, default)
        except TypeError:
            pass
    if isinstance(config, Mapping):
        cur: Any = config
        for part in path.split("."):
            if not isinstance(cur, Mapping) or part not in cur:
                return default
            cur = cur[part]
        return cur
    return default


def _config_get_bool(config: Any, path: str, default: bool = False) -> bool:
    getter = getattr(config, "get_bool", None)
    if callable(getter):
        try:
            return bool(getter(path, default))
        except TypeError:
            try:
                return bool(getter(path, default, None))
            except Exception:
                pass
        except Exception:
            pass
    value = _config_get(config, path, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _config_get_int(config: Any, path: str, default: int, *, minimum: int = 1, maximum: int = 300) -> int:
    try:
        value = int(_config_get(config, path, default))
    except Exception:
        value = int(default)
    return max(minimum, min(maximum, value))


def _tool_loop_max_steps_raw(config: Any) -> Any:
    value = _config_get(config, TOOL_LOOP_MAX_STEPS_CONFIG_KEY, None)
    if value is not None:
        return value
    for key in TOOL_LOOP_MAX_STEPS_ALIAS_KEYS:
        value = _config_get(config, key, None)
        if value is not None:
            return value
    return TOOL_LOOP_MAX_STEPS_DEFAULT


def clamp_owner_tool_loop_max_steps(value: Any) -> int:
    """Coerce owner-controlled tool-loop max_steps.

    Owner private chat has full toolbox permission.  The only protection kept
    here is the nonsensical lower bound of 1; there is intentionally no upper
    clamp (AstrBot itself can be configured to very large values).
    """
    try:
        parsed = int(value)
    except Exception:
        parsed = TOOL_LOOP_MAX_STEPS_DEFAULT
    return max(TOOL_LOOP_MAX_STEPS_MIN, parsed)


def get_owner_tool_loop_max_steps(config: Any = None) -> int:
    return clamp_owner_tool_loop_max_steps(_tool_loop_max_steps_raw(config))


def _config_set(config: Any, path: str, value: Any) -> bool:
    setter = getattr(config, "set", None)
    if callable(setter):
        try:
            return bool(setter(path, value))
        except TypeError:
            pass
        except Exception:
            return False

    target: Any = None
    if isinstance(config, Mapping):
        target = config
    else:
        data = getattr(config, "data", None)
        if isinstance(data, Mapping):
            target = data
        overrides = getattr(config, "overrides", None)
        if target is None and isinstance(overrides, Mapping):
            target = overrides

    if target is None:
        return False

    try:
        current = target
        parts = path.split(".")
        for part in parts[:-1]:
            child = current.get(part) if isinstance(current, Mapping) else None
            if not isinstance(child, dict):
                child = {}
                current[part] = child
            current = child
        current[parts[-1]] = value
        return True
    except Exception:
        return False


def set_owner_tool_loop_max_steps(config: Any, value: Any) -> tuple[bool, int, str]:
    steps = clamp_owner_tool_loop_max_steps(value)
    ok = _config_set(config, TOOL_LOOP_MAX_STEPS_CONFIG_KEY, steps)
    return ok, steps, TOOL_LOOP_MAX_STEPS_CONFIG_KEY
