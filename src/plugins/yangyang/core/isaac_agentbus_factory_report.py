#!/usr/bin/env python3
"""Read-only AgentBus/Nekro worker factory report for I叔.

This module only reads controller/dispatcher/validator artifacts under the
workspace run directory. It never dispatches workers, never calls network, and
never mutates production state.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

DEFAULT_RUNS_DIR = Path(
    os.environ.get(
        "NEKRO_WORKER_RUNS_DIR",
        "/root/data/data/workspaces/default_FriendMessage_335059272/nekro_worker_runs",
    )
)
ISOLATION_FILE = DEFAULT_RUNS_DIR / "isolation_list.json"
LEASE_DIR = Path(os.environ.get("NEKRO_WORKER_LEASE_DIR", "/tmp/nekro_cc_workspace_leases"))
BACKENDS: dict[str, dict[str, Any]] = {
    "gpt": {"label": "GPT 黑奴房", "prefix": "xw", "count": 30},
    "mimo": {"label": "小米 MiMo 黑奴房", "prefix": "mi", "count": 10},
    "mmx": {"label": "MMX 黑奴房", "prefix": "mmx", "count": 10},
}
MODULE_SERVICES: dict[str, dict[str, Any]] = {
    "nonebot": {"title": "NoneBot / 秧秧", "units": ["yangyang-nonebot.service", "napcat-3940223711.service"], "readiness_units": ["yangyang-nonebot.service", "napcat-3940223711.service"]},
    "astrbot": {"title": "AstrBot / 娅娅", "units": ["astrbot.service", "napcat-2690087239.service"], "readiness_units": ["astrbot.service", "napcat-2690087239.service"]},
    "astrbot_yangyang": {"title": "AstrBot / 秧秧", "units": ["astrbot-yangyang.service", "napcat-3776215950.service"], "readiness_units": ["astrbot-yangyang.service", "napcat-3776215950.service"]},
    "nekro": {"title": "Nekro Agents", "units": ["nekro-agent-yaya.service", "nekro-agent-yangyang.service"], "readiness_units": ["nekro-agent-yaya.service"]},
}


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists() or not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - readonly report must fail-soft
        return {"_read_error": f"{type(exc).__name__}: {exc}"}


def _safe_read_text(path: Path, limit: int = 1200) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[:limit]
    except Exception as exc:  # noqa: BLE001
        return f"[read_error:{type(exc).__name__}]"


def _iter_run_dirs(runs_dir: Path) -> list[Path]:
    if not runs_dir.exists() or not runs_dir.is_dir():
        return []
    out = [p for p in runs_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
    return sorted(out, key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)


def _pick_latest_run(runs_dir: Path, *, require_validation: bool = True) -> Path | None:
    for d in _iter_run_dirs(runs_dir):
        if require_validation and not (d / "validation_report.json").exists():
            continue
        return d
    return None


def _summarize_validation(report: Mapping[str, Any]) -> dict[str, Any]:
    items = list(report.get("items") or []) if isinstance(report, Mapping) else []
    worker_rows: list[dict[str, Any]] = []
    total_write_artifacts = 0
    total_py_compile = 0
    pytest_runs = 0
    pytest_failed = 0
    for item in items[:20]:
        if not isinstance(item, Mapping):
            continue
        wav = dict(item.get("write_artifact_validation") or {})
        files = list(wav.get("files") or [])
        py_compile = list(wav.get("py_compile") or [])
        pytest_info = wav.get("pytest") if isinstance(wav.get("pytest"), Mapping) else {}
        total_write_artifacts += int(wav.get("count") or len(files) or 0)
        total_py_compile += len(py_compile)
        if pytest_info:
            pytest_runs += 1
            if int(pytest_info.get("exit_code") or 0) != 0:
                pytest_failed += 1
        worker_rows.append({
            "workspace_id": str(item.get("workspace_id") or ""),
            "validation_status": str(item.get("validation_status") or ""),
            "worker_state": str(item.get("worker_state") or ""),
            "tool_calls": int(item.get("tool_calls") or 0),
            "events_lines": int(item.get("events_lines") or 0),
            "write_artifacts_count": int(wav.get("count") or len(files) or 0),
            "py_compile_count": len(py_compile),
            "pytest_exit_code": (pytest_info or {}).get("exit_code"),
            "issues_count": len(list(item.get("issues") or [])),
            "warnings_count": len(list(item.get("warnings") or [])),
        })
    return {
        "overall_status": str(report.get("overall_status") or "UNKNOWN"),
        "generated_at": str(report.get("generated_at") or ""),
        "counts_by_validation_status": dict(report.get("counts_by_validation_status") or {}),
        "global_issues_count": len(list(report.get("global_issues") or [])),
        "worker_count": len(items),
        "total_write_artifacts": total_write_artifacts,
        "total_py_compile": total_py_compile,
        "pytest_runs": pytest_runs,
        "pytest_failed": pytest_failed,
        "workers": worker_rows,
    }



def _fmt_ts(ts: float | int | None) -> str:
    if not ts:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return ""


def _run_dirs(runs_dir: Path, limit: int = 24) -> list[Path]:
    return _iter_run_dirs(runs_dir)[:limit]


def _read_first_json(paths: list[Path]) -> dict[str, Any]:
    for path in paths:
        data = _safe_read_json(path)
        if data:
            return data
    return {}


def _has_any_path(path: Path, names: tuple[str, ...]) -> bool:
    return any((path / name).exists() for name in names)


def _has_any_glob(path: Path, patterns: tuple[str, ...]) -> bool:
    return any(next(path.glob(pattern), None) is not None for pattern in patterns)


def _run_state(path: Path, dispatcher: Mapping[str, Any], manifest: Mapping[str, Any], controller: Mapping[str, Any]) -> str:
    raw = str(dispatcher.get("state") or "").lower()
    if _has_any_path(path, ("abort_marker.json", "ABORTED", "aborted")):
        return "ABORTED"
    if _has_any_path(path, ("manual_closure_report.md", "manual_closure.json", "pure_offline_closure.md")):
        return "MANUAL_CLOSED"
    if raw in {"running", "active", "leased", "dispatching"}:
        return "RUNNING"
    if raw in {"dry_run", "dry-run", "plan", "planned"}:
        return "DRY_RUN"
    if _has_any_path(path, ("manifest.json", "pure_offline_manifest.json", "write_artifacts/manifest.json")) or manifest.get("items"):
        return "COLLECTED"
    if _has_any_path(path, ("controller_report.json", "pure_offline_controller_report.json")) or controller:
        return "STOPPED"
    return raw.upper() if raw else "UNKNOWN"


def _review_state(path: Path, activity_state: str) -> str:
    if activity_state == "RUNNING":
        return "RUNNING"
    if activity_state == "ABORTED":
        return "ABORTED"
    if activity_state == "MANUAL_CLOSED":
        return "FORENSIC_DONE"
    if _has_any_path(path, ("validation_report.json", "write_artifacts/validation_report.json", "pure_offline_validation_report.json")):
        return "VALIDATED_NEED_HUMAN"
    if _has_any_path(path, ("manifest.json", "write_artifacts/manifest.json", "controller_report.json")) or _has_any_glob(path, ("*/events.jsonl", "events.jsonl")):
        return "NEED_REVIEW"
    return "UNKNOWN"


def _artifact_state(path: Path, manifest: Mapping[str, Any]) -> str:
    if _has_any_path(path, ("manifest.json", "pure_offline_manifest.json", "write_artifacts/manifest.json")) or manifest.get("items"):
        return "COLLECTED"
    if _has_any_glob(path, ("*/events.jsonl", "events.jsonl")):
        return "EVENTS_ONLY"
    return "NO_MANIFEST"


def _report_state(path: Path) -> str:
    if _has_any_path(path, ("controller_report.json", "pure_offline_controller_report.json")):
        return "HAS_CONTROLLER"
    if _has_any_path(path, ("manual_closure_report.md", "manual_closure.json", "pure_offline_closure.md")):
        return "MANUAL_CLOSURE"
    if _has_any_path(path, ("abort_marker.json", "ABORTED", "aborted")):
        return "ABORTED"
    return "NO_CONTROLLER_REPORT"


def _summarize_run(path: Path) -> dict[str, Any]:
    controller = _safe_read_json(path / "controller_report.json")
    dispatcher = _safe_read_json(path / "dispatcher_status.json")
    validation = _read_first_json([path / "validation_report.json", path / "write_artifacts" / "validation_report.json", path / "pure_offline_validation_report.json"])
    manifest = _read_first_json([path / "manifest.json", path / "write_artifacts" / "manifest.json", path / "pure_offline_manifest.json"])
    activity = _run_state(path, dispatcher, manifest, controller)
    status_counts: dict[str, int] = {}
    for status_path in sorted(path.glob("*/status.json")):
        data = _safe_read_json(status_path)
        state = str(data.get("state") or "unknown")
        status_counts[state] = status_counts.get(state, 0) + 1
    markers = []
    raw_state = str(dispatcher.get("state") or "")
    if raw_state:
        markers.append(f"dispatcher:{raw_state}")
    if _has_any_path(path, ("manifest.json", "write_artifacts/manifest.json", "pure_offline_manifest.json")):
        markers.append("artifact_manifest")
    if _has_any_path(path, ("controller_report.json", "pure_offline_controller_report.json")):
        markers.append("controller_report")
    if _has_any_path(path, ("validation_report.json", "write_artifacts/validation_report.json", "pure_offline_validation_report.json")):
        markers.append("validation_report")
    if status_counts:
        markers.append("status_counts=" + ",".join(f"{k}:{v}" for k, v in sorted(status_counts.items())))
    return {
        "name": path.name,
        "mtime": path.stat().st_mtime,
        "mtime_text": _fmt_ts(path.stat().st_mtime),
        "backend": controller.get("backend") or dispatcher.get("backend_key") or dispatcher.get("backend") or "",
        "decision": ((controller.get("decision") or {}).get("decision") if isinstance(controller.get("decision"), Mapping) else None) or dispatcher.get("state") or "unknown",
        "pool_size": controller.get("pool_size") or len(dispatcher.get("workers_selected") or []) or len(manifest.get("items") or []),
        "validation": controller.get("validation_overall_status") or validation.get("overall_status") or "",
        "activity_state": activity,
        "review_state": _review_state(path, activity),
        "artifact_state": _artifact_state(path, manifest),
        "report_state": _report_state(path),
        "counts": validation.get("counts_by_validation_status") or manifest.get("counts_by_state") or {},
        "markers": markers,
        "workers_selected": list(dispatcher.get("workers_selected") or [])[:20],
        "skipped": list(dispatcher.get("skipped") or manifest.get("skipped") or [])[:20],
    }


def _load_isolation() -> dict[str, Any]:
    data = _safe_read_json(ISOLATION_FILE)
    return data if data else {"items": []}


def _load_leases() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not LEASE_DIR.exists():
        return out
    now = time.time()
    for path in LEASE_DIR.glob("*.json"):
        item = _safe_read_json(path)
        backend = str(item.get("backend") or "")
        wid = str(item.get("workspace_id") or "")
        if not backend or not wid:
            continue
        expires_at = float(item.get("expires_at") or 0)
        item["active"] = expires_at > now
        item["expires_at_text"] = _fmt_ts(expires_at)
        out[f"{backend}:{wid}"] = item
    return out


def _workspace_backend(workspace_id: str) -> str:
    for backend, meta in BACKENDS.items():
        if workspace_id.startswith(str(meta["prefix"])):
            return backend
    return "unknown"


def _latest_worker_results(runs_dir: Path, scan_runs: int = 120) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for run_dir in _run_dirs(runs_dir, scan_runs):
        manifest = _read_first_json([run_dir / "manifest.json", run_dir / "write_artifacts" / "manifest.json", run_dir / "pure_offline_manifest.json"])
        validation = _read_first_json([run_dir / "validation_report.json", run_dir / "write_artifacts" / "validation_report.json", run_dir / "pure_offline_validation_report.json"])
        vmap = {str(item.get("workspace_id") or ""): item for item in validation.get("items", []) if isinstance(item, Mapping)}
        dispatcher = _safe_read_json(run_dir / "dispatcher_status.json")
        backend = dispatcher.get("backend_key") or dispatcher.get("backend") or ""
        for item in manifest.get("items", []) or []:
            if not isinstance(item, Mapping):
                continue
            wid = str(item.get("workspace_id") or "")
            if not wid:
                continue
            bkey = backend if backend in BACKENDS else _workspace_backend(wid)
            key = f"{bkey}:{wid}"
            if key in latest:
                continue
            val = vmap.get(wid, {})
            latest[key] = {
                "backend": bkey,
                "workspace_id": wid,
                "run": run_dir.name,
                "run_mtime_text": _fmt_ts(run_dir.stat().st_mtime),
                "state": item.get("state"),
                "events_lines": item.get("events_lines"),
                "final_chars": item.get("final_chars"),
                "validation_status": val.get("validation_status"),
                "issues": val.get("issues") or [],
                "warnings": val.get("warnings") or [],
            }
    return latest


def _worker_pool_status(runs_dir: Path) -> dict[str, Any]:
    isolation_items = [item for item in _load_isolation().get("items", []) or [] if isinstance(item, Mapping) and item.get("isolated", True)]
    isolated = {f"{item.get('backend') or _workspace_backend(str(item.get('workspace_id') or ''))}:{item.get('workspace_id')}": dict(item) for item in isolation_items if item.get("workspace_id")}
    leases = _load_leases()
    latest = _latest_worker_results(runs_dir)
    backends: dict[str, Any] = {}
    all_items: list[dict[str, Any]] = []
    for backend, meta in BACKENDS.items():
        items = []
        stats = {"total": int(meta["count"]), "idle": 0, "leased": 0, "isolated": 0, "unknown": 0}
        for index in range(1, int(meta["count"]) + 1):
            wid = f"{meta['prefix']}{index}"
            key = f"{backend}:{wid}"
            iso = isolated.get(key)
            lease = leases.get(key)
            last = latest.get(key, {})
            state = "isolated" if iso else ("leased" if lease and lease.get("active") else "idle")
            stats[state] += 1
            if not last:
                stats["unknown"] += 1
            row = {"backend": backend, "backend_label": meta["label"], "workspace_id": wid, "state": state, "isolated": bool(iso), "isolation": iso, "lease": lease, "last": last}
            items.append(row)
            all_items.append(row)
        backends[backend] = {"meta": meta, "stats": stats, "items": items}
    return {"backends": backends, "items": all_items}


def _systemd_show(unit: str) -> dict[str, Any]:
    props = ["Id", "LoadState", "ActiveState", "SubState", "MainPID", "NRestarts", "ExecMainStatus"]
    cmd = ["systemctl", "show", unit, "--no-pager"] + [f"--property={prop}" for prop in props]
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=4, check=False)
    except Exception as exc:
        return {"unit": unit, "ok": False, "active": False, "error": type(exc).__name__}
    data: dict[str, Any] = {"unit": unit, "ok": proc.returncode == 0}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    data["active"] = data.get("ActiveState") == "active"
    if not data["ok"]:
        data["error"] = (proc.stderr or proc.stdout)[-240:]
    return data


def _module_health() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, cfg in MODULE_SERVICES.items():
        services = [_systemd_show(unit) for unit in cfg["units"]]
        readiness_units = set(cfg.get("readiness_units") or cfg["units"])
        readiness = [svc for svc in services if svc.get("unit") in readiness_units]
        active_count = sum(1 for svc in services if svc.get("active"))
        readiness_active = sum(1 for svc in readiness if svc.get("active"))
        out[key] = {
            "title": cfg["title"],
            "units": cfg["units"],
            "services": services,
            "active_count": active_count,
            "total": len(services),
            "online": active_count == len(services),
            "readiness_active_count": readiness_active,
            "readiness_total": len(readiness),
            "readiness_online": readiness_active == len(readiness),
            "connection_marker_in_tail": False,
            "connection_marker_reason": "not_scanned_in_yy_web",
        }
    return out


def _extended_factory_context(runs_dir: Path) -> dict[str, Any]:
    recent_runs = [_summarize_run(path) for path in _run_dirs(runs_dir, 32)]
    health = _module_health()
    offline = [item.get("title") for item in health.values() if not item.get("readiness_online", item.get("online"))]
    return {
        "generated_at": _fmt_ts(time.time()),
        "recent_runs": recent_runs,
        "latest": recent_runs[0] if recent_runs else None,
        "worker_pool": _worker_pool_status(runs_dir),
        "health": health,
        "readiness": {
            "status": "READY" if not offline else "CAUTION",
            "warning_count": len(offline),
            "warnings": [{"code": "offline_services", "services": offline}] if offline else [],
            "summary": {"recent_runs_scanned": len(recent_runs), "offline_services": len(offline)},
        },
    }

def build_agentbus_factory_report(runs_dir: str | Path | None = None) -> dict[str, Any]:
    """Build a readonly summary of the latest worker-factory run."""
    base = Path(runs_dir) if runs_dir is not None else DEFAULT_RUNS_DIR
    latest = _pick_latest_run(base, require_validation=True)
    report: dict[str, Any] = {
        "schema_version": "isaac.agentbus_factory_report.v1",
        "read_only": True,
        "runs_dir_exists": base.exists(),
        "runs_dir_name": base.name,
        "latest_run": None,
        "status": "NO_RUNS",
        "effects": {
            "shell_used": False,
            "network_used": False,
            "executor_used": False,
            "host_action_executed": False,
            "write_performed": False,
        },
    }
    if latest is None:
        return report

    validation = _safe_read_json(latest / "validation_report.json")
    manifest = _safe_read_json(latest / "manifest.json")
    controller = _safe_read_json(latest / "controller_report.json")
    dispatcher = _safe_read_json(latest / "dispatcher_status.json")
    summary_text = _safe_read_text(latest / "validation_summary.md", limit=1600)

    validation_summary = _summarize_validation(validation)
    write_counts = dict(manifest.get("write_artifacts_counts") or {}) if isinstance(manifest, Mapping) else {}
    decision = dict(controller.get("decision") or {}) if isinstance(controller, Mapping) else {}

    report.update({
        "status": validation_summary.get("overall_status") or "UNKNOWN",
        "latest_run": {
            "name": latest.name,
            "path_redacted": True,
            "validation_report_present": bool((latest / "validation_report.json").exists()),
            "manifest_present": bool((latest / "manifest.json").exists()),
            "controller_report_present": bool((latest / "controller_report.json").exists()),
            "dispatcher_status_present": bool((latest / "dispatcher_status.json").exists()),
        },
        "validation": validation_summary,
        "write_artifacts_counts": {
            "events_files": int(write_counts.get("events_files") or 0),
            "lines": int(write_counts.get("lines") or 0),
            "write_calls": int(write_counts.get("write_calls") or 0),
            "collected": int(write_counts.get("collected") or 0),
            "skipped": int(write_counts.get("skipped") or 0),
            "errors": int(write_counts.get("errors") or 0),
        },
        "controller": {
            "schema_version": str(controller.get("schema_version") or ""),
            "title": str(controller.get("title") or ""),
            "backend": str(controller.get("backend") or ""),
            "pool_size": controller.get("pool_size"),
            "validation_overall_status": str(controller.get("validation_overall_status") or ""),
            "decision": str(decision.get("decision") or ""),
            "reason": str(decision.get("reason") or ""),
            "retry_rounds": int((controller.get("retry_history") or {}).get("rounds") or 0) if isinstance(controller.get("retry_history"), Mapping) else 0,
        },
        "dispatcher": {
            "state": str(dispatcher.get("state") or ""),
            "backend_key": str(dispatcher.get("backend_key") or ""),
            "workers_selected": list(dispatcher.get("workers_selected") or [])[:20],
            "skipped": list(dispatcher.get("skipped") or [])[:20],
        },
    })
    report.update(_extended_factory_context(base))
    return report


def format_agentbus_factory_report(report: Mapping[str, Any]) -> str:
    """Render a short QQ-safe report. Avoid secrets; include only run metadata."""
    status = str(report.get("status") or "UNKNOWN")
    latest = dict(report.get("latest_run") or {})
    validation = dict(report.get("validation") or {})
    counts = dict(report.get("write_artifacts_counts") or {})
    controller = dict(report.get("controller") or {})
    dispatcher = dict(report.get("dispatcher") or {})
    lines = [
        "AgentBus 工厂只读报告：",
        f"latest_run={latest.get('name') or '-'} status={status}",
        (
            "validation "
            f"workers={validation.get('worker_count', 0)} "
            f"counts={validation.get('counts_by_validation_status', {})} "
            f"write_artifacts={validation.get('total_write_artifacts', 0)} "
            f"py_compile={validation.get('total_py_compile', 0)} "
            f"pytest_runs={validation.get('pytest_runs', 0)} "
            f"pytest_failed={validation.get('pytest_failed', 0)}"
        ),
        (
            "collector "
            f"events_files={counts.get('events_files', 0)} "
            f"write_calls={counts.get('write_calls', 0)} "
            f"collected={counts.get('collected', 0)} "
            f"errors={counts.get('errors', 0)}"
        ),
        (
            "controller "
            f"backend={controller.get('backend') or '-'} "
            f"decision={controller.get('decision') or '-'} "
            f"reason={controller.get('reason') or '-'}"
        ),
        (
            "dispatcher "
            f"state={dispatcher.get('state') or '-'} "
            f"workers={dispatcher.get('workers_selected') or []}"
        ),
    ]
    workers = list(validation.get("workers") or [])
    if workers:
        first = dict(workers[0])
        lines.append(
            "first_worker "
            f"id={first.get('workspace_id') or '-'} "
            f"status={first.get('validation_status') or '-'} "
            f"state={first.get('worker_state') or '-'} "
            f"tools={first.get('tool_calls', 0)} "
            f"events={first.get('events_lines', 0)} "
            f"write_artifacts={first.get('write_artifacts_count', 0)}"
        )
    lines.append("read_only=true shell_used=false host_action_executed=false")
    return "\n".join(lines)


__all__ = ["build_agentbus_factory_report", "format_agentbus_factory_report", "DEFAULT_RUNS_DIR"]
