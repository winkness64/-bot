from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import _config_get


PROJECT_ROOT = Path(__file__).resolve().parents[5]


def _resolve_workspace_root(config: Any = None, project_root: str | Path | None = None) -> Path:
    """Return the default working directory for owner-only engineering tools.

    The light package no longer enforces a workspace sandbox. This value is the
    default cwd for `shell` / `python` invocations and the implicit base for
    relative paths, but absolute paths anywhere on the host filesystem are
    accepted by the owner-private executor.
    """
    fallback = Path(project_root or PROJECT_ROOT).resolve()
    raw = str(
        _config_get(config, "owner_toolbox_light_workspace_root", "")
        or _config_get(config, "owner_engineering_toolbox_workspace_root", "")
        or ""
    ).strip()
    if not raw:
        return fallback
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = fallback / candidate
    try:
        return candidate.resolve()
    except Exception:
        return fallback


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _resolve_user_path(raw_path: Any, root: Path, *, for_write: bool = False) -> tuple[bool, Path | None, str, str]:
    """Resolve a user-supplied path with no workspace sandbox gate.

    Owner-private calls have full host filesystem visibility. The `root` is
    kept as the implicit base for relative inputs and as the default cwd for
    shell/python, but it is not enforced as a boundary. `rel` is preserved for
    downstream display: it falls back to the absolute path when the resolved
    location lives outside the default cwd.
    """
    text = str(raw_path or ".").strip() or "."
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve(strict=False)
    except Exception as exc:
        return False, None, text, f"bad_path:{exc.__class__.__name__}"
    if for_write:
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return False, None, text, f"mkdir_failed:{exc.__class__.__name__}"
    try:
        rel = resolved.relative_to(root).as_posix()
    except Exception:
        rel = resolved.as_posix()
    return True, resolved, rel or resolved.as_posix() or ".", "ok"
