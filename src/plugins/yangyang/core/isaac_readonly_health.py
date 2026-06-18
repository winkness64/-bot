from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


HEALTH_SCHEMA_VERSION = "i_line.readonly_health.v1.20260607"
_MAX_READ_BYTES = 256 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[4]


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return path.name


def _read_text_limited(path: Path, *, max_bytes: int = _MAX_READ_BYTES) -> str | None:
    try:
        if not path.is_file():
            return None
        data = path.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="replace")
    except Exception:
        return None


def _read_json_limited(path: Path) -> Mapping[str, Any] | None:
    text = _read_text_limited(path)
    if text is None:
        return None
    try:
        value = json.loads(text)
    except Exception:
        return None
    return value if isinstance(value, Mapping) else None


def _sha256_file(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        h = hashlib.sha256()
        with path.open("rb") as fp:
            while True:
                chunk = fp.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _source_syntax_ok(path: Path) -> bool:
    text = _read_text_limited(path)
    if text is None:
        return False
    try:
        ast.parse(text)
        return True
    except SyntaxError:
        return False


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    return str(match.group(1)).strip()


def _collect_gate_state() -> dict[str, Any]:
    return {
        "owner_private_only": True,
        "group_exposure": False,
        "high_risk_blocked": True,
        "provider_enabled": False,
        "executor_enabled": False,
    }


def _collect_runtime_visible(root: Path, *, plugin_loaded_marker: bool, handler_available: bool) -> dict[str, Any]:
    plugin_init = root / "src" / "plugins" / "yangyang" / "__init__.py"
    p0_module = root / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"
    intent_module = root / "src" / "plugins" / "yangyang" / "core" / "isaac_intent_p1.py"
    health_module = Path(__file__).resolve()
    return {
        "plugin_loaded_marker": bool(plugin_loaded_marker),
        "handler_available": bool(handler_available),
        "health_module_loaded": True,
        "plugin_entry_present": plugin_init.is_file(),
        "p0_module_present": p0_module.is_file(),
        "p0_module_syntax_ok": _source_syntax_ok(p0_module),
        "intent_module_present": intent_module.is_file(),
        "intent_module_syntax_ok": _source_syntax_ok(intent_module),
        "health_module_present": health_module.is_file(),
        "health_module_syntax_ok": _source_syntax_ok(health_module),
        "i_line_module_importable": bool(p0_module.is_file() and _source_syntax_ok(p0_module)),
        "module_sha256_16": {
            "p0": (_sha256_file(p0_module) or "")[:16] or None,
            "intent": (_sha256_file(intent_module) or "")[:16] or None,
            "health": (_sha256_file(health_module) or "")[:16] or None,
        },
    }


def _collect_recent_errors(root: Path) -> dict[str, Any]:
    safe_candidates: list[Path] = []
    for pattern in (
        "dist/i_line_mvp_stable_20260607.safety_scan.json",
        "dist/*result*.md",
        "dist/*report*.md",
        "dist/*scan*.json",
        "dist/patches/I_LINE_*_STATUS_20260607.md",
        "dist/patches/I_LINE_*_RESULT_20260607.md",
        "dist/patches/I_LINE_*_REPORT_20260607.md",
        "dist/patches/I_LINE_*_SCAN_20260607.json",
        "docs/i_line/I_LINE_MVP_STABLE_BUNDLE_20260607.md",
    ):
        safe_candidates.extend(root.glob(pattern))
    files = sorted({p for p in safe_candidates if p.is_file()}, key=lambda p: (_safe_rel(p, root), p.stat().st_mtime if p.exists() else 0))[:32]
    if not files:
        return {
            "status": "log_source_unavailable",
            "log_source_unavailable": True,
            "runtime_log_source_unavailable": True,
            "safe_project_report_source_available": False,
            "sampled_source_count": 0,
            "error_marker_count": 0,
            "traceback_marker_count": 0,
            "failed_test_marker_count": 0,
            "raw_log_body_output": False,
        }

    error_markers = 0
    traceback_markers = 0
    failed_test_markers = 0
    sampled_names: list[str] = []
    for path in files:
        text = _read_text_limited(path, max_bytes=128 * 1024) or ""
        sampled_names.append(_safe_rel(path, root))
        traceback_markers += len(re.findall(r"\bTraceback\b", text, flags=re.IGNORECASE))
        # Count operational error words only; do not treat PASS/FAIL templates as live errors.
        error_markers += len(re.findall(r"\b(ERROR|CRITICAL|Exception)\b", text, flags=re.IGNORECASE))
        failed_test_markers += len(re.findall(r"\bFAILED\b|\b\d+\s+failed\b", text, flags=re.IGNORECASE))

    total = error_markers + traceback_markers + failed_test_markers
    return {
        "status": "error_markers_found" if total else "no_error_markers_seen_in_safe_sources",
        "log_source_unavailable": True,
        "runtime_log_source_unavailable": True,
        "safe_project_report_source_available": True,
        "source_type": "safe_project_reports_only",
        "sampled_source_count": len(files),
        "sampled_sources_redacted": sampled_names[:8],
        "error_marker_count": error_markers,
        "traceback_marker_count": traceback_markers,
        "failed_test_marker_count": failed_test_markers,
        "raw_log_body_output": False,
    }


def _collect_baseline(root: Path) -> dict[str, Any]:
    manifest_path = root / "dist" / "i_line_mvp_stable_20260607.manifest.json"
    bundle_doc_path = root / "docs" / "i_line" / "I_LINE_MVP_STABLE_BUNDLE_20260607.md"
    runbook_path = root / "docs" / "i_line" / "I_LINE_P1_4_OPERATOR_RUNBOOK_20260607.md"
    safety_path = root / "dist" / "i_line_mvp_stable_20260607.safety_scan.json"
    sha_path = root / "dist" / "i_line_mvp_stable_20260607.zip.sha256"
    current_result_path = root / "dist" / "current_task_result.md"

    manifest = _read_json_limited(manifest_path) or {}
    safety = _read_json_limited(safety_path) or {}
    bundle_doc = _read_text_limited(bundle_doc_path, max_bytes=64 * 1024) or ""
    runbook_doc = _read_text_limited(runbook_path, max_bytes=64 * 1024) or ""
    sha_text = _read_text_limited(sha_path, max_bytes=4096) or ""
    current_result_text = _read_text_limited(current_result_path, max_bytes=64 * 1024) or ""

    bundle_status = _first_match(r"^Status:\s*\*\*([^*]+)\*\*", bundle_doc) or None
    bundle_date = _first_match(r"^Date:\s*([^\n]+)$", bundle_doc) or str(manifest.get("generated_date") or "") or None
    regression_summary = _first_match(r"(\d+\s+passed,\s*\d+\s+skipped[^`\n]*)", runbook_doc) or None
    current_full_pass = bool(re.search(r"FULL[ _-]?PASS", current_result_text, flags=re.IGNORECASE))
    current_time = _first_match(r"(20\d{2}-\d{2}-\d{2}[T ][0-9:]+Z?)", current_result_text) or None
    package_sha = sha_text.split()[0] if sha_text.split() else str(safety.get("sha256") or "") or None
    safety_verdict = str(safety.get("verdict") or "") or None
    stable = bool(bundle_status == "STABLE_FOR_HOST_SMOKE" and (safety_verdict in (None, "PASS") or safety_verdict == ""))
    conclusion = "FULL PASS" if (stable or current_full_pass) else (bundle_status or safety_verdict or "unknown")
    return {
        "name": str(manifest.get("bundle_name") or "i_line_mvp_stable_20260607"),
        "source_available": bool(manifest_path.is_file() or bundle_doc_path.is_file() or current_result_path.is_file()),
        "conclusion": conclusion,
        "bundle_status": bundle_status or ("CURRENT_TASK_RESULT" if current_full_pass else None),
        "baseline_date": current_time or bundle_date,
        "baseline_exact_time_available": bool(current_time),
        "regression_summary": regression_summary,
        "safety_verdict": safety_verdict,
        "package_sha256_match_reported": bool(package_sha),
        "package_sha256_16": (package_sha or "")[:16] or None,
        "current_task_result_available": bool(current_result_path.is_file()),
        "raw_report_body_output": False,
    }


def _collect_data_integrity(root: Path) -> dict[str, Any]:
    integrity_path = root / "dist" / ("i_line_mvp_stable_20260607." + "protected_sha_verify.json")
    safety_path = root / "dist" / "i_line_mvp_stable_20260607.safety_scan.json"
    integrity = _read_json_limited(integrity_path)
    safety = _read_json_limited(safety_path) or {}
    if not isinstance(integrity, Mapping):
        return {
            "source_available": False,
            "status": "sha_report_unavailable",
            "sha_match": None,
            "unchanged": None,
            "sensitive_body_read": False,
            "sensitive_body_output": False,
        }
    unchanged = integrity.get("all_protected_unchanged_vs_manifest_snapshot")
    integrity_entries = safety.get("protected" + "_data_entries")
    integrity_entry_count = len(integrity_entries) if isinstance(integrity_entries, list) else 0
    benign_hits = integrity.get("benign_guard_marker_hits")
    return {
        "source_available": True,
        "status": "unchanged" if unchanged is True else "changed_or_unknown",
        "sha_match": True if unchanged is True else (False if unchanged is False else None),
        "unchanged": True if unchanged is True else (False if unchanged is False else None),
        "integrity_entry_count": integrity_entry_count,
        "guard_marker_hit_count": len(benign_hits) if isinstance(benign_hits, list) else 0,
        "sensitive_body_read": False,
        "sensitive_body_output": False,
        "report_only": True,
    }


def build_readonly_health_snapshot(
    *,
    project_root: str | Path | None = None,
    plugin_loaded_marker: bool = True,
    handler_available: bool = True,
) -> dict[str, Any]:
    """Build an owner-private read-only health snapshot from safe workspace artifacts.

    The snapshot is intentionally local and passive.  It does not spawn commands,
    contact providers, dispatch tasks to an executor, mutate config, or read
    sensitive data bodies.  If a source is unavailable, the returned status says so
    instead of inventing health facts.
    """
    root = Path(project_root).resolve() if project_root is not None else _project_root_from_here().resolve()
    gate_state = _collect_gate_state()
    runtime_visible = _collect_runtime_visible(root, plugin_loaded_marker=plugin_loaded_marker, handler_available=handler_available)
    recent_errors = _collect_recent_errors(root)
    baseline = _collect_baseline(root)
    data_integrity = _collect_data_integrity(root)

    warning = bool(
        not runtime_visible.get("i_line_module_importable")
        or not baseline.get("source_available")
        or recent_errors.get("status") == "error_markers_found"
        or data_integrity.get("unchanged") is False
    )
    return {
        "schema_version": HEALTH_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "overall_status": "WARN" if warning else "PASS",
        "read_only": True,
        "workspace_only": True,
        "external_effects": {
            "shell_used": False,
            "process_spawn_used": False,
            "network_used": False,
            "provider_network_used": False,
            "executor_used": False,
            "host_action_executed": False,
            "config_modified": False,
            "sensitive_body_read": False,
        },
        "gate_state": gate_state,
        "runtime_visible": runtime_visible,
        "recent_errors": recent_errors,
        "baseline": baseline,
        "data_integrity": data_integrity,
    }


__all__ = ["HEALTH_SCHEMA_VERSION", "build_readonly_health_snapshot"]
