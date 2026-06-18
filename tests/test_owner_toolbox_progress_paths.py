from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "plugins" / "yangyang" / "core" / "owner_toolbox" / "progress.py"
SPEC = importlib.util.spec_from_file_location("owner_toolbox_progress_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
progress_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = progress_mod
SPEC.loader.exec_module(progress_mod)


def test_progress_audit_default_root_follows_module_location_not_legacy_opt() -> None:
    path = progress_mod.resolve_progress_audit_path({"owner_toolbox_native_audit_path": "logs/owner_toolbox_native_audit.jsonl"})
    expected = Path(progress_mod.__file__).resolve().parents[5] / "logs" / "owner_toolbox_native_audit.jsonl"

    assert path == expected
    assert path.as_posix() != "/opt/yangyang_nonebot/logs/owner_toolbox_native_audit.jsonl"


def test_progress_audit_explicit_project_root_still_wins(tmp_path: Path) -> None:
    path = progress_mod.resolve_progress_audit_path(
        {"owner_toolbox_native_audit_path": "logs/owner_toolbox_native_audit.jsonl"},
        project_root=tmp_path,
    )

    assert path == tmp_path.resolve() / "logs" / "owner_toolbox_native_audit.jsonl"
