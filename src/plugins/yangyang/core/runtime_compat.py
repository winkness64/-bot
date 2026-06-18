from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any



_LEGACY_PROJECT_ROOT_PREFIXES: tuple[str, ...] = ("/opt/yangyang_nonebot",)


def _strip_legacy_project_root_prefix(value: Path) -> Path:
    """Return a relative path when *value* is under a known legacy project root.

    The project has been moved behind a symlink before.  Persisted runtime
    config may still contain absolute paths such as
    /opt/yangyang_nonebot/src/plugins/yangyang/data/memory.  Treat those as
    project-relative so the active installation can derive the live path from
    data_dir/project_root instead of following stale literals.
    """
    text = value.as_posix()
    for legacy in _LEGACY_PROJECT_ROOT_PREFIXES:
        prefix = legacy.rstrip("/")
        if text == prefix:
            return Path(".")
        if text.startswith(prefix + "/"):
            return Path(text[len(prefix) + 1 :])
    return value


def _infer_project_root_from_data_dir(data_dir: str | Path | None) -> Path | None:
    """Infer project root from .../src/plugins/yangyang/data when possible."""
    if data_dir is None:
        return None
    try:
        data_path = Path(data_dir).resolve()
        parts = data_path.parts
        if len(parts) >= 4 and parts[-4:] == ("src", "plugins", "yangyang", "data"):
            return data_path.parents[3]
    except Exception:
        return None
    return None


RELEVANT_PLUGIN_CONFIG_KEYS = {
    "memory_root",
    "memory_short_term_capture_enabled",
    "memory_prompt_injection_enabled",
    "memory_prompt_injection_private_enabled",
    "memory_prompt_injection_group_mention_enabled",
    "memory_prompt_injection_group_silent_enabled",
    "memory_daily_summary_enabled",
    "memory_short_term_limit",
    "memory_pipeline_interval_minutes",
    "memory_capture_audit_enabled",
    "memory_capture_audit_path",
}


def deep_merge_dicts(base: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    result = copy.deepcopy(base)
    if not isinstance(overlay, dict):
        return result
    for key, value in overlay.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = deep_merge_dicts(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def extract_plugin_config_mapping(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, dict):
        return copy.deepcopy(config)
    data = getattr(config, "data", None)
    if isinstance(data, dict):
        return copy.deepcopy(data)
    if hasattr(config, "items"):
        try:
            return copy.deepcopy(dict(config.items()))
        except Exception:
            pass

    extracted: dict[str, Any] = {}
    getter = getattr(config, "get", None)
    if callable(getter):
        for key in RELEVANT_PLUGIN_CONFIG_KEYS:
            try:
                value = getter(key, None)
            except TypeError:
                try:
                    value = getter(key)
                except Exception:
                    continue
            except Exception:
                continue
            if value is not None:
                extracted[key] = copy.deepcopy(value)
    return extracted


def load_context_plugin_config(context: Any) -> dict[str, Any]:
    if context is None:
        return {}
    getter = getattr(context, "get_config", None)
    if not callable(getter):
        return {}
    try:
        return extract_plugin_config_mapping(getter())
    except Exception:
        return {}


def resolve_plugin_init_config(
    *,
    context: Any = None,
    config: Any = None,
    plugin_config: Any = None,
) -> dict[str, Any]:
    context_mapping = load_context_plugin_config(context)
    explicit_mapping = deep_merge_dicts(
        extract_plugin_config_mapping(config),
        extract_plugin_config_mapping(plugin_config),
    )
    return deep_merge_dicts(context_mapping, explicit_mapping)


def escape_log_preview(text: Any, limit: int | None = None) -> str:
    value = str(text or "")
    value = value.replace("\\", "\\\\")
    value = value.replace("\r", "\\r").replace("\n", "\\n")
    if limit is not None and limit >= 0 and len(value) > limit:
        if limit <= 1:
            return value[:limit]
        return value[: limit - 1] + "…"
    return value


def resolve_memory_root(
    *,
    plugin_config: dict[str, Any] | None = None,
    data_dir: str | Path | None = None,
    project_root: str | Path | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    effective_env = env or os.environ
    raw_value = effective_env.get("YANGYANG_MEMORY_ROOT")
    if raw_value is None:
        raw_value = (plugin_config or {}).get("memory_root")

    base_candidates = [
        Path(data_dir).resolve() if data_dir else None,
        Path(project_root).resolve() if project_root else None,
        Path(cwd).resolve() if cwd else None,
        Path.cwd().resolve(),
    ]
    base_dir = next((item for item in base_candidates if item is not None), Path.cwd().resolve())

    if raw_value is None or str(raw_value).strip() == "":
        return (Path(data_dir).resolve() / "memory") if data_dir else (base_dir / "data" / "memory")

    candidate = Path(str(raw_value).strip()).expanduser()
    if candidate.is_absolute():
        stripped = _strip_legacy_project_root_prefix(candidate)
        if stripped != candidate:
            legacy_anchor = (
                Path(project_root).resolve()
                if project_root
                else _infer_project_root_from_data_dir(data_dir)
            )
            if legacy_anchor is not None:
                return (legacy_anchor / stripped).resolve()
            return (base_dir / stripped).resolve()
        return candidate.resolve()
    return (base_dir / candidate).resolve()
