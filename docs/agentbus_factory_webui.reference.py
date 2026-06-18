#!/usr/bin/env python3
"""Read-only Agent Bus / bot health WebUI.

Purpose v0.1:
- one local page for Nekro worker factory runs
- worker slot status / isolation / leases
- NoneBot + NapCat health
- AstrBot + NapCat health
- rolling logs for each module

Security posture:
- read-only; no restart/deploy/write actions
- never prints env/key/token/base_url secrets beyond existing localhost service metadata
- supports token-file auth before binding to LAN
- token query is redacted from access logs
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import hmac
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

WORKSPACE = Path("/root/data/data/workspaces/default_FriendMessage_335059272")
RUN_ROOT = WORKSPACE / "nekro_worker_runs"
SCRIPT_ROOT = Path("/root/data/data/workspaces/scripts")
ISOLATION_FILE = RUN_ROOT / "isolation_list.json"
LEASE_DIR = Path("/tmp/nekro_cc_workspace_leases")
YANGYANG_REPO = Path("/opt/yangyang_nonebot")
YANGYANG_RUNTIME_CONFIG = YANGYANG_REPO / "data" / "runtime_config.json"
MODEL_PROFILES = {
    "v4_flash": {"label": "DeepSeek V4 Flash", "provider": "deepseek", "model": "deepseek-v4-flash", "api_key_env": "DEEPSEEK_API_KEY", "base_url_env": ""},
    "v4_pro": {"label": "DeepSeek V4 Pro", "provider": "deepseek", "model": "deepseek-v4-pro", "api_key_env": "DEEPSEEK_API_KEY", "base_url_env": ""},
    "gpt_5_4": {"label": "GPT 5.4", "provider": "openai_compat", "model": "gpt-5.4", "api_key_env": "GPT_API_KEY", "base_url_env": "GPT_BASE_URL"},
    "gpt_5_5": {"label": "GPT 5.5 xhigh", "provider": "openai_compat", "model": "gpt-5.5", "api_key_env": "GPT_API_KEY", "base_url_env": "GPT_BASE_URL"},
    "m2_7": {"label": "MiniMax M2.7", "provider": "openai_compat", "model": "MiniMax-M2.7", "api_key_env": "MINIMAX_API_KEY", "base_url_env": "MINIMAX_BASE_URL"},
    "gemini_3_1_pro_high": {"label": "Gemini 3.1 Pro High", "provider": "openai_compat", "model": "gemini-3.1-pro-high", "api_key_env": "GEMINI_API_KEY", "base_url_env": "GEMINI_BASE_URL"},
}

BACKENDS = {
    "gpt": {"label": "GPT 黑奴房", "prefix": "xw", "count": 30},
    "mimo": {"label": "小米 MiMo 黑奴房", "prefix": "mi", "count": 10},
    "mmx": {"label": "MMX 黑奴房", "prefix": "mmx", "count": 10},
}

MODULE_SERVICES = {
    "nonebot": {
        "title": "NoneBot / 秧秧",
        "units": ["yangyang-nonebot.service", "napcat-3940223711.service"],
        "main": "yangyang-nonebot.service",
        "bot": "napcat-3940223711.service",
    },
    "astrbot": {
        "title": "AstrBot / 娅娅",
        "units": ["astrbot.service", "napcat-2690087239.service"],
        "main": "astrbot.service",
        "bot": "napcat-2690087239.service",
    },
    "astrbot_yangyang": {
        "title": "AstrBot / 秧秧",
        "units": ["astrbot-yangyang.service", "napcat-3776215950.service"],
        "main": "astrbot-yangyang.service",
        "bot": "napcat-3776215950.service",
    },
    "nekro": {
        "title": "Nekro Agents",
        "units": ["nekro-agent-yaya.service", "nekro-agent-yangyang.service"],
        "readiness_units": ["nekro-agent-yaya.service"],
        "main": "nekro-agent-yaya.service",
        "bot": "nekro-agent-yangyang.service",
    },
}

LOG_TARGETS = {"factory", "workers", "nonebot", "astrbot", "astrbot_yangyang", "nekro"}


def now_ts() -> float:
    return time.time()


def fmt_ts(ts: float | int | None) -> str:
    if not ts:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return ""


def run_cmd(cmd: list[str], timeout: int = 8) -> dict[str, Any]:
    try:
        p = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {"ok": p.returncode == 0, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except Exception as e:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": repr(e)}




def nested_get(data: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def nested_set(data: dict[str, Any], path: str, value: Any) -> None:
    cur: dict[str, Any] = data
    parts = path.split(".")
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def load_yangyang_runtime_config() -> dict[str, Any]:
    try:
        if YANGYANG_RUNTIME_CONFIG.exists():
            data = json.loads(YANGYANG_RUNTIME_CONFIG.read_text(encoding="utf-8") or "{}")
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def save_yangyang_runtime_config(data: dict[str, Any]) -> None:
    YANGYANG_RUNTIME_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    backup = YANGYANG_RUNTIME_CONFIG.with_suffix(YANGYANG_RUNTIME_CONFIG.suffix + f".bak_webui_model_{time.strftime('%Y%m%d-%H%M%S')}")
    if YANGYANG_RUNTIME_CONFIG.exists():
        backup.write_text(YANGYANG_RUNTIME_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = YANGYANG_RUNTIME_CONFIG.with_suffix(YANGYANG_RUNTIME_CONFIG.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(YANGYANG_RUNTIME_CONFIG)


def model_config_summary() -> dict[str, Any]:
    cfg = load_yangyang_runtime_config()
    profiles: list[dict[str, Any]] = []
    for pid, meta in MODEL_PROFILES.items():
        provider_cfg = dict(nested_get(cfg, f"providers.{pid}", {}) or {})
        model_cfg = dict(nested_get(cfg, f"models.{pid}", {}) or {})
        provider = str(provider_cfg.get("provider") or meta["provider"])
        model = str(provider_cfg.get("model") or model_cfg.get("model") or meta["model"])
        api_key_env = str(provider_cfg.get("api_key_env") or meta.get("api_key_env") or "")
        base_url_env = str(provider_cfg.get("base_url_env") or meta.get("base_url_env") or "")
        profiles.append({
            "id": pid,
            "label": meta["label"],
            "provider": provider,
            "model": model,
            "enabled": bool(provider_cfg.get("enabled", model_cfg.get("enabled", pid in {"v4_flash", "v4_pro"}))),
            "api_key_env": api_key_env,
            "base_url_env": base_url_env,
            "api_key_env_set": bool(os.getenv(api_key_env)) if api_key_env else True,
            "base_url_env_set": bool(os.getenv(base_url_env)) if base_url_env else True,
        })
    return {
        "runtime_config": str(YANGYANG_RUNTIME_CONFIG),
        "isaac_model_profile": str(nested_get(cfg, "isaac.model_profile", "v4_pro") or "v4_pro"),
        "private_profile": str(nested_get(cfg, "model_profile_switcher.active_profile_private", "v4_flash") or "v4_flash"),
        "group_profile": str(nested_get(cfg, "model_profile_switcher.active_profile_group", "v4_flash") or "v4_flash"),
        "profiles": profiles,
        "notes": ["Secrets are never displayed or written here; only env var names and presence are shown.", "Changing model config may require restarting yangyang-nonebot.service."],
    }


def apply_model_config(payload: dict[str, Any]) -> dict[str, Any]:
    scope = str(payload.get("scope") or "isaac").strip()
    profile = str(payload.get("profile") or "").strip()
    if profile not in MODEL_PROFILES:
        return {"ok": False, "error": "invalid_profile"}
    if scope not in {"isaac", "private", "group"}:
        return {"ok": False, "error": "invalid_scope"}
    cfg = load_yangyang_runtime_config()
    meta = MODEL_PROFILES[profile]
    provider_cfg = dict(nested_get(cfg, f"providers.{profile}", {}) or {})
    provider_cfg.update({
        "provider": meta["provider"],
        "model": meta["model"],
        "api_key_env": meta.get("api_key_env", ""),
        "timeout": int(payload.get("timeout") or (180 if profile == "gpt_5_5" else 120)),
        "cooldown_on_fail": 300,
        "enabled": True,
    })
    if meta.get("base_url_env"):
        provider_cfg["base_url_env"] = meta["base_url_env"]
    nested_set(cfg, f"providers.{profile}", provider_cfg)
    nested_set(cfg, f"models.{profile}", {"model": meta["model"], "enabled": True})
    if scope == "isaac":
        nested_set(cfg, "isaac.model_profile", profile)
    elif scope == "private":
        nested_set(cfg, "model_profile_switcher.active_profile_private", profile)
    elif scope == "group":
        nested_set(cfg, "model_profile_switcher.active_profile_group", profile)
    save_yangyang_runtime_config(cfg)
    out = model_config_summary()
    out.update({"ok": True, "changed_scope": scope, "changed_profile": profile})
    return out


def read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"_read_error": repr(e), "_path": str(path)}


def read_first_json(paths: list[Path]) -> dict[str, Any]:
    for path in paths:
        data = read_json(path)
        if data:
            return data
    return {}


def tail_file(path: Path, max_chars: int = 20000) -> str:
    try:
        if not path.exists():
            return f"[missing] {path}\n"
        data = path.read_bytes()
        if len(data) > max_chars:
            data = data[-max_chars:]
        return data.decode("utf-8", errors="replace")
    except Exception as e:
        return f"[read_error] {path}: {e!r}\n"


def pid_alive(pid: Any) -> bool:
    try:
        p = int(pid)
    except Exception:
        return False
    if p <= 0:
        return False
    try:
        os.kill(p, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def workspace_backend(workspace_id: str) -> str:
    for key, b in BACKENDS.items():
        if workspace_id.startswith(str(b["prefix"])):
            return key
    return "unknown"


def run_logical_mtime(p: Path) -> float:
    """Sort runs by creation/dispatcher time, not later forensic writes.

    Recovery manifests and manual closure files are intentionally written after
    the run is over; using directory mtime would make old forensic samples jump
    to the top of the dashboard.
    """
    candidates: list[float] = []
    for name in ("controller_task.json", "initial_tasks.json", "dispatcher_status.json", "tasks.json"):
        fp = p / name
        if fp.exists():
            try:
                candidates.append(fp.stat().st_mtime)
            except OSError:
                pass
    for status in p.glob("*/status.json"):
        try:
            data = read_json(status)
            for key in ("started_at", "finished_at", "updated_at"):
                if data.get(key):
                    candidates.append(float(data[key]))
        except Exception:
            pass
    if candidates:
        return min(candidates)
    return p.stat().st_mtime


def run_dirs(limit: int = 80) -> list[Path]:
    if not RUN_ROOT.exists():
        return []
    dirs = []
    for p in RUN_ROOT.iterdir():
        if not p.is_dir():
            continue
        if p.name == RUN_ROOT.name:
            continue
        try:
            dirs.append(p)
        except Exception:
            pass
    dirs.sort(key=run_logical_mtime, reverse=True)
    return dirs[:limit]


def validation_item_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in report.get("items", []) or []:
        wid = item.get("workspace_id")
        if wid:
            out[str(wid)] = item
    return out


def has_any_path(p: Path, names: tuple[str, ...] | list[str]) -> bool:
    return any((p / name).exists() for name in names)


def has_any_glob(p: Path, patterns: tuple[str, ...] | list[str]) -> bool:
    for pattern in patterns:
        try:
            if any(p.glob(pattern)):
                return True
        except Exception:
            continue
    return False


def has_manual_closure(p: Path) -> bool:
    return has_any_path(p, ("manual_closure_report.json", "manual_closure_report.md", "pure_offline_closure.md"))


def has_abort_marker(p: Path) -> bool:
    return has_any_glob(p, ("ABORTED_BY_OWNER*", "ABORTED*", "OWNER_STOP*"))


def has_controller_report(p: Path) -> bool:
    # Some vetted runs write JSON + human summary, not controller_report.md.
    return has_any_path(p, ("controller_report.json", "controller_report.md", "controller_summary.md"))


def has_validation_report(p: Path) -> bool:
    return has_any_path(p, ("validation_report.json", "validation_report.md", "validation_summary.md", "pure_offline_validation_report.json", "write_artifacts/validation_report.json", "write_artifacts/validation_summary.md"))


def has_artifact_manifest(p: Path) -> bool:
    return has_any_path(p, ("manifest.json", "pure_offline_manifest.json", "write_artifacts/manifest.json"))


def has_events_trace(p: Path) -> bool:
    return has_any_glob(p, ("*/events.jsonl", "events.jsonl"))


def collect_worker_statuses(p: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sf in sorted(p.glob("*/status.json")):
        data = read_json(sf)
        if not data:
            continue
        data.setdefault("workspace_id", sf.parent.name)
        data["_status_path"] = str(sf)
        out.append(data)
    return out


def status_counts_from_files(p: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for st in collect_worker_statuses(p):
        state = str(st.get("state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    return counts


def run_has_active_lease(p: Path) -> bool:
    leases = load_leases()
    for st in collect_worker_statuses(p):
        wid = str(st.get("workspace_id") or "")
        if not wid:
            continue
        key = f"{workspace_backend(wid)}:{wid}"
        lease = leases.get(key) or {}
        if not lease.get("active"):
            continue
        # If both status and lease carry lease_id, require them to match.  If not,
        # still treat an active lease as a live clue rather than declaring stale.
        sid = str(st.get("lease_id") or "")
        lid = str(lease.get("lease_id") or "")
        if not sid or not lid or sid == lid:
            return True
    return False


def is_stale_running(p: Path, stale_after_seconds: int = 30 * 60) -> bool:
    """Best-effort stale-running detector for the dashboard.

    It never contacts sandboxes and never mutates runs.  A run is stale when it
    still says running but has no active lease and the run/status timestamps are
    older than the freshness window.  Manual closure / abort markers are handled
    by run_activity_state before this helper.
    """
    if run_has_active_lease(p):
        return False
    now = now_ts()
    statuses = collect_worker_statuses(p)
    running = [st for st in statuses if str(st.get("state") or "").lower() in {"running", "active", "leased", "dispatching"}]
    if not running:
        # Dispatcher can say running even if no status files were ever written.
        return (now - p.stat().st_mtime) > stale_after_seconds
    newest = 0.0
    for st in running:
        for key in ("updated_at", "finished_at", "started_at", "mtime"):
            try:
                newest = max(newest, float(st.get(key) or 0))
            except Exception:
                pass
        try:
            newest = max(newest, Path(str(st.get("_status_path"))).stat().st_mtime)
        except Exception:
            pass
    if not newest:
        newest = p.stat().st_mtime
    return (now - newest) > stale_after_seconds


def run_activity_state(p: Path, dispatcher: dict[str, Any], manifest: dict[str, Any], controller: dict[str, Any]) -> str:
    """Return a purely mechanical run state, not a quality verdict.

    Precedence matters: an old dispatcher_status.json can keep saying
    ``running`` after owner abort / manual offline closure.  Those forensic
    markers must win over stale live-state strings, otherwise the dashboard lies.
    """
    raw = str(dispatcher.get("state") or "").lower()
    if has_abort_marker(p):
        return "ABORTED"
    if has_manual_closure(p):
        return "MANUAL_CLOSED"
    if raw in {"dry_run", "dry-run", "plan", "planned"}:
        return "DRY_RUN"
    if raw in {"running", "active", "leased", "dispatching"}:
        return "STALE_RUNNING" if is_stale_running(p) else "RUNNING"
    if has_artifact_manifest(p) or manifest.get("items"):
        return "COLLECTED"
    if has_controller_report(p) or controller:
        return "STOPPED"
    if raw in {"done", "completed", "finished", "stopped", "cancelled", "canceled"}:
        return "STOPPED"
    return "UNKNOWN"


def review_queue_state(p: Path, activity_state: str) -> str:
    """Dashboard review marker: only says human review is needed/done."""
    if activity_state == "RUNNING":
        return "RUNNING"
    if activity_state == "STALE_RUNNING":
        return "NEED_CLOSURE"
    if activity_state == "DRY_RUN":
        return "DRY_RUN"
    if activity_state == "ABORTED":
        return "ABORTED"
    if activity_state == "MANUAL_CLOSED":
        return "FORENSIC_DONE"
    if has_validation_report(p):
        return "VALIDATED_NEED_HUMAN"
    if has_artifact_manifest(p) or has_controller_report(p) or has_events_trace(p):
        return "NEED_REVIEW"
    return "UNKNOWN"


def artifact_collection_state(p: Path, manifest: dict[str, Any]) -> str:
    if has_artifact_manifest(p) or manifest.get("items"):
        return "COLLECTED"
    if has_events_trace(p):
        return "EVENTS_ONLY"
    return "NO_MANIFEST"


def report_collection_state(p: Path) -> str:
    if has_controller_report(p):
        return "HAS_CONTROLLER"
    if has_manual_closure(p):
        return "MANUAL_CLOSURE"
    if has_abort_marker(p):
        return "ABORTED"
    return "NO_CONTROLLER_REPORT"


def run_markers(p: Path, dispatcher: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    raw = str(dispatcher.get("state") or "").lower()
    if raw:
        markers.append(f"dispatcher:{raw}")
    if has_abort_marker(p):
        markers.append("abort_marker")
    if has_manual_closure(p):
        markers.append("manual_closure")
    if has_artifact_manifest(p):
        markers.append("artifact_manifest")
    elif has_events_trace(p):
        markers.append("events_only")
    if has_controller_report(p):
        markers.append("controller_report")
    if has_validation_report(p):
        markers.append("validation_report")
    sc = status_counts_from_files(p)
    if sc:
        markers.append("status_counts=" + ",".join(f"{k}:{v}" for k, v in sorted(sc.items())))
    return markers

def summarize_run(p: Path) -> dict[str, Any]:
    c = read_json(p / "controller_report.json")
    d = read_json(p / "dispatcher_status.json")
    v = read_first_json([p / "validation_report.json", p / "write_artifacts" / "validation_report.json", p / "pure_offline_validation_report.json"])
    m = read_first_json([p / "manifest.json", p / "write_artifacts" / "manifest.json", p / "pure_offline_manifest.json"])
    decision = ((c.get("decision") or {}).get("decision") if c else None) or d.get("state") or "unknown"
    backend = c.get("backend") or d.get("backend_key") or d.get("backend") or ""
    pool = c.get("pool_size") or len(d.get("workers_selected") or []) or len((m.get("items") or []))
    validation = c.get("validation_overall_status") or v.get("overall_status") or ((d.get("validation") or {}).get("overall_status") if d else None)
    counts = v.get("counts_by_validation_status") or m.get("counts_by_state") or {}
    activity_state = run_activity_state(p, d, m, c)
    review_state = review_queue_state(p, activity_state)
    artifact_state = artifact_collection_state(p, m)
    report_state = report_collection_state(p)
    reaped = 0
    for item in m.get("items", []) or []:
        st = item.get("status") or {}
        if isinstance(st, dict) and st.get("watchdog_reaped"):
            reaped += 1
    return {
        "name": p.name,
        "path": str(p),
        "mtime": run_logical_mtime(p),
        "mtime_text": fmt_ts(run_logical_mtime(p)),
        # Keep raw decision/validation in JSON detail for forensic inspection,
        # but the dashboard renders only mechanical states below.
        "decision": decision,
        "backend": backend,
        "pool_size": pool,
        "validation": validation,
        "activity_state": activity_state,
        "review_state": review_state,
        "artifact_state": artifact_state,
        "report_state": report_state,
        "counts": counts,
        "has_controller": has_controller_report(p),
        "has_manifest": has_artifact_manifest(p),
        "has_validation": has_validation_report(p),
        "status_counts_from_files": status_counts_from_files(p),
        "markers": run_markers(p, d),
        "workers_selected": d.get("workers_selected") or [],
        "skipped": d.get("skipped") or (m.get("skipped") if m else []) or [],
        "watchdog_reaped_count": reaped,
    }


def load_isolation() -> dict[str, Any]:
    data = read_json(ISOLATION_FILE)
    if not data:
        return {"items": []}
    data.setdefault("items", [])
    return data


def active_isolation_by_key() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in load_isolation().get("items", []) or []:
        if not item.get("isolated", True):
            continue
        backend = str(item.get("backend") or workspace_backend(str(item.get("workspace_id") or "")))
        wid = str(item.get("workspace_id") or "")
        if backend and wid:
            out[f"{backend}:{wid}"] = item
    return out


def load_leases() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not LEASE_DIR.exists():
        return out
    now = now_ts()
    for p in LEASE_DIR.glob("*.json"):
        item = read_json(p)
        if not item:
            continue
        backend = str(item.get("backend") or workspace_backend(str(item.get("workspace_id") or "")))
        wid = str(item.get("workspace_id") or "")
        if not backend or not wid:
            continue
        expires_at = float(item.get("expires_at") or 0)
        active = pid_alive(item.get("pid")) or expires_at > now
        item["lease_file"] = str(p)
        item["active"] = active
        item["expires_at_text"] = fmt_ts(expires_at)
        out[f"{backend}:{wid}"] = item
    return out


def latest_worker_results(scan_runs: int = 120) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for rd in run_dirs(scan_runs):
        manifest = read_first_json([rd / "manifest.json", rd / "write_artifacts" / "manifest.json", rd / "pure_offline_manifest.json"])
        if not manifest:
            continue
        vmap = validation_item_map(read_first_json([rd / "validation_report.json", rd / "write_artifacts" / "validation_report.json", rd / "pure_offline_validation_report.json"]))
        dispatcher = read_json(rd / "dispatcher_status.json")
        backend = dispatcher.get("backend_key") or dispatcher.get("backend") or ""
        for item in manifest.get("items", []) or []:
            wid = str(item.get("workspace_id") or "")
            if not wid:
                continue
            bkey = backend if backend in BACKENDS else workspace_backend(wid)
            key = f"{bkey}:{wid}"
            if key in latest:
                continue
            val = vmap.get(wid, {})
            st = item.get("status") or {}
            latest[key] = {
                "backend": bkey,
                "workspace_id": wid,
                "run": rd.name,
                "run_path": str(rd),
                "run_mtime": rd.stat().st_mtime,
                "run_mtime_text": fmt_ts(rd.stat().st_mtime),
                "state": item.get("state"),
                "events_lines": item.get("events_lines"),
                "final_chars": item.get("final_chars"),
                "missing_required_artifacts": item.get("missing_required_artifacts") or [],
                "validation_status": val.get("validation_status"),
                "issues": val.get("issues") or [],
                "warnings": val.get("warnings") or [],
                "watchdog_reaped": bool(st.get("watchdog_reaped")) if isinstance(st, dict) else False,
                "watchdog_reap_reason": st.get("watchdog_reap_reason") if isinstance(st, dict) else None,
            }
    return latest


def worker_pool_status() -> dict[str, Any]:
    isolated = active_isolation_by_key()
    leases = load_leases()
    latest = latest_worker_results()
    backends: dict[str, Any] = {}
    all_items: list[dict[str, Any]] = []
    for bkey, meta in BACKENDS.items():
        prefix = str(meta["prefix"])
        count = int(meta["count"])
        items = []
        stats = {"total": count, "idle": 0, "leased": 0, "isolated": 0, "unknown": 0}
        for i in range(1, count + 1):
            wid = f"{prefix}{i}"
            key = f"{bkey}:{wid}"
            iso = isolated.get(key)
            lease = leases.get(key)
            last = latest.get(key, {})
            state = "idle"
            if iso:
                state = "isolated"
                stats["isolated"] += 1
            elif lease and lease.get("active"):
                state = "leased"
                stats["leased"] += 1
            else:
                stats["idle"] += 1
            if not last:
                stats["unknown"] += 1
            item = {
                "backend": bkey,
                "backend_label": meta["label"],
                "workspace_id": wid,
                "state": state,
                "isolated": bool(iso),
                "isolation": iso,
                "lease": lease,
                "last": last,
            }
            items.append(item)
            all_items.append(item)
        backends[bkey] = {"meta": meta, "stats": stats, "items": items}
    return {"backends": backends, "items": all_items, "isolation_file": str(ISOLATION_FILE), "lease_dir": str(LEASE_DIR)}


def systemd_show(unit: str) -> dict[str, Any]:
    props = [
        "Id", "LoadState", "ActiveState", "SubState", "MainPID", "NRestarts",
        "ExecMainStatus", "ExecMainStartTimestamp", "ExecMainExitTimestamp",
    ]
    cmd = ["systemctl", "show", unit, "--no-pager"] + [f"--property={p}" for p in props]
    r = run_cmd(cmd, timeout=6)
    data: dict[str, Any] = {"unit": unit, "ok": r["ok"]}
    for line in r.get("stdout", "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k] = v
    if not r["ok"]:
        data["error"] = (r.get("stderr") or r.get("stdout") or "").strip()[-300:]
    data["active"] = data.get("ActiveState") == "active"
    return data


def journal(units: list[str], lines: int = 160) -> str:
    cmd = ["journalctl", "--no-pager", "-n", str(max(1, min(lines, 2000)))]
    for u in units:
        cmd.extend(["-u", u])
    r = run_cmd(cmd, timeout=12)
    text = r.get("stdout") or r.get("stderr") or ""
    return text[-60000:]


CONNECTION_MARKER_PATTERNS = [
    ("astrbot_event_bus_aiocqhttp", re.compile(r"core\.event_bus:74].*\[default\(aiocqhttp\)\]", re.I)),
    ("nonebot_onebot_event", re.compile(r"\[SUCCESS\]\s+nonebot\s+\|\s+OneBot V11 .*\[(?:message|notice|request|meta_event)", re.I)),
    ("message_sent", re.compile(r"\bmessage_sent\b|发送\s*->", re.I)),
    ("websocket_connected", re.compile(r"connected|Connection.*open|WebSocket.*connect|OneBot.*connect|Bot .*connected|已连接|连接成功", re.I)),
]


def detect_connection_marker(log_tail: str) -> tuple[bool, str]:
    for label, pattern in CONNECTION_MARKER_PATTERNS:
        if pattern.search(log_tail or ""):
            return True, label
    return False, ""


def module_health() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, cfg in MODULE_SERVICES.items():
        services = [systemd_show(u) for u in cfg["units"]]
        active_count = sum(1 for s in services if s.get("active"))
        readiness_units = cfg.get("readiness_units") or cfg["units"]
        readiness_unit_set = set(readiness_units)
        readiness_services = [s for s in services if s.get("unit") in readiness_unit_set]
        readiness_active_count = sum(1 for s in readiness_services if s.get("active"))
        log_tail = journal(cfg["units"], lines=320)
        connected, marker = detect_connection_marker(log_tail)
        out[key] = {
            "title": cfg["title"],
            "units": cfg["units"],
            "services": services,
            "active_count": active_count,
            "total": len(services),
            "online": active_count == len(services),
            "readiness_units": list(readiness_units),
            "readiness_active_count": readiness_active_count,
            "readiness_total": len(readiness_services),
            "readiness_online": readiness_active_count == len(readiness_services),
            "connection_marker_in_tail": connected,
            "connection_marker_reason": marker,
        }
    return out


def factory_summary(limit: int = 24) -> dict[str, Any]:
    runs = [summarize_run(p) for p in run_dirs(limit)]
    iso = load_isolation()
    active_iso = [x for x in iso.get("items", []) or [] if x.get("isolated", True)]
    return {
        "run_root": str(RUN_ROOT),
        "recent_runs": runs,
        "latest": runs[0] if runs else None,
        "isolation_file": str(ISOLATION_FILE),
        "active_isolated_count": len(active_iso),
        "active_isolated": active_iso,
    }


def factory_readiness() -> dict[str, Any]:
    runs = [summarize_run(p) for p in run_dirs(30)]
    workers = worker_pool_status()
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    ok_items: list[dict[str, Any]] = []

    active_iso = []
    for backend, info in (workers.get("backends") or {}).items():
        stats = info.get("stats") or {}
        if int(stats.get("isolated") or 0) > 0:
            warnings.append({"code": "isolated_workers", "message": f"{backend} has isolated workers", "count": stats.get("isolated")})
        active_iso.extend([x for x in info.get("items") or [] if x.get("isolated")])

    running = [r for r in runs if r.get("activity_state") == "RUNNING"]
    stale = [r for r in runs if r.get("activity_state") == "STALE_RUNNING"]
    aborted = [r for r in runs if r.get("activity_state") == "ABORTED"]
    failed_validation = [r for r in runs if str(r.get("validation") or "").upper() in {"FAIL_RETRY", "BLOCKED", "ERROR"}]
    now = now_ts()
    failure_signal_window_seconds = 6 * 3600
    actionable_failed_validation = [
        r for r in failed_validation
        if r.get("activity_state") not in {"ABORTED", "MANUAL_CLOSED", "DRY_RUN"}
        and (now - float(r.get("mtime") or 0)) <= failure_signal_window_seconds
    ]
    no_manifest = [r for r in runs[:10] if r.get("artifact_state") == "NO_MANIFEST" and r.get("activity_state") not in {"DRY_RUN", "STOPPED", "ABORTED"}]
    no_report = [r for r in runs[:10] if r.get("report_state") == "NO_CONTROLLER_REPORT" and r.get("activity_state") == "COLLECTED"]

    if stale:
        issues.append({"code": "stale_running_runs", "message": "stale running runs need closure", "runs": [r["name"] for r in stale[:8]]})
    if running:
        warnings.append({"code": "active_running_runs", "message": "runs are currently marked RUNNING", "runs": [r["name"] for r in running[:8]]})
    if actionable_failed_validation:
        warnings.append({"code": "actionable_failed_validation_runs", "message": "recent actionable runs have FAIL/BLOCKED validation", "runs": [r["name"] for r in actionable_failed_validation[:8]]})
    elif failed_validation:
        ok_items.append({"code": "historical_failed_validation_classified", "message": "older/classified FAIL/BLOCKED validation samples are kept for forensics but ignored for production readiness", "count": len(failed_validation)})
    if no_manifest:
        warnings.append({"code": "missing_manifest_runs", "message": "recent non-dry-run items have no manifest", "runs": [r["name"] for r in no_manifest[:8]]})
    if no_report:
        warnings.append({"code": "missing_controller_report", "message": "collected runs missing controller report", "runs": [r["name"] for r in no_report[:8]]})
    if aborted:
        ok_items.append({"code": "aborted_runs_classified", "message": "aborted runs are classified and not treated as live", "count": len(aborted)})

    services = module_health()
    offline = [h.get("title") for h in services.values() if not h.get("readiness_online", h.get("online"))]
    optional_partial = [h.get("title") for h in services.values() if not h.get("online") and h.get("readiness_online", h.get("online"))]
    if offline:
        warnings.append({"code": "offline_services", "message": "some readiness-required services are not fully active", "services": offline})
    if optional_partial:
        ok_items.append({"code": "optional_services_partial", "message": "some optional service units are inactive but ignored for production readiness", "services": optional_partial})

    blocking = len(issues)
    caution = len(warnings)
    status = "READY" if blocking == 0 and caution == 0 else ("CAUTION" if blocking == 0 else "BLOCKED")
    return {
        "status": status,
        "blocking_count": blocking,
        "warning_count": caution,
        "issues": issues,
        "warnings": warnings,
        "ok_items": ok_items,
        "summary": {
            "recent_runs_scanned": len(runs),
            "running": len(running),
            "stale_running": len(stale),
            "aborted": len(aborted),
            "failed_validation": len(failed_validation),
            "actionable_failed_validation": len(actionable_failed_validation),
            "isolated_workers": len(active_iso),
        },
    }


def full_summary() -> dict[str, Any]:
    return {
        "generated_at": fmt_ts(now_ts()),
        "factory": factory_summary(),
        "workers": worker_pool_status(),
        "health": module_health(),
        "readiness": factory_readiness(),
    }


def log_factory(lines: int = 200) -> str:
    chunks = [f"# Factory log snapshot @ {fmt_ts(now_ts())}\n"]
    for rd in reversed(run_dirs(6)):
        chunks.append(f"\n===== {rd.name} =====\n")
        for name in ["controller_summary.md", "validation_summary.md", "manual_closure_report.md", "pure_offline_closure.md", "dispatcher_status.json"]:
            p = rd / name
            if p.exists():
                chunks.append(f"\n--- {name} ---\n")
                chunks.append(tail_file(p, 12000))
    return "".join(chunks)[-80000:]


def log_workers(lines: int = 200) -> str:
    wp = worker_pool_status()
    chunks = [f"# Worker status snapshot @ {fmt_ts(now_ts())}\n"]
    chunks.append("\n## Isolation\n")
    chunks.append(json.dumps(load_isolation(), ensure_ascii=False, indent=2))
    chunks.append("\n\n## Active / stale leases\n")
    chunks.append(json.dumps(load_leases(), ensure_ascii=False, indent=2))
    chunks.append("\n\n## Backend stats\n")
    stats = {k: v["stats"] for k, v in wp.get("backends", {}).items()}
    chunks.append(json.dumps(stats, ensure_ascii=False, indent=2))
    chunks.append("\n\n## Recent worker tails\n")
    for rd in reversed(run_dirs(4)):
        for st in sorted(rd.glob("*/status.json"))[:80]:
            chunks.append(f"\n--- {rd.name}/{st.parent.name}/status.json ---\n")
            chunks.append(tail_file(st, 3000))
    return "".join(chunks)[-80000:]


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
TOOL_RESULT_RE = re.compile(r"Tool `[^`]+` Result:|使用工具：|参数：\{|\"stdout\":|\"stderr\":|\"exit_code\":")
NOISY_LOG_RE = re.compile(r"BiliVideo/DBG|AutoDetect|AccessCheck|Matcher\(type='message'.*running complete|Event will be handled by Matcher|MemoryPipeline: run_once|Tasks: pipeline completed")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text or "")


def clean_log_text(text: str, target: str) -> str:
    """Human-friendly log view.

    Raw logs stay available via mode=raw.  Clean mode removes ANSI color,
    collapses huge tool-result lines, hides noisy plugin/debug chatter, and
    marks old NapCat logs so historical bot nicknames don't look like current
    runtime identity.
    """
    out: list[str] = []
    skipped_tool = 0
    skipped_noise = 0
    for raw_line in strip_ansi(text).splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if TOOL_RESULT_RE.search(line) and len(line) > 220:
            skipped_tool += 1
            continue
        if NOISY_LOG_RE.search(line):
            skipped_noise += 1
            continue
        if len(line) > 1200:
            line = line[:1200] + " ... [truncated]"
        # Old NapCat log files can contain historical account names such as
        # 西格莉卡.  Prefix them in clean mode so users don't confuse them with
        # current AstrBot runtime identity.
        if target in {"astrbot", "astrbot_yangyang", "nonebot"} and re.match(r"^0[1-9]-|^1[0-2]-", line):
            line = "[历史NapCat] " + line
        out.append(line)
    header = f"# Clean log view target={target} @ {fmt_ts(now_ts())}\n"
    if skipped_tool or skipped_noise:
        header += f"# hidden: tool_result_lines={skipped_tool}, noisy_lines={skipped_noise}\n"
        header += "# 切换到 原始日志 可查看完整内容。\n"
    return header + "\n".join(out)[-78000:]


def log_target(target: str, lines: int = 200, mode: str = "clean") -> str:
    if target == "factory":
        text = log_factory(lines)
    elif target == "workers":
        text = log_workers(lines)
    elif target in MODULE_SERVICES:
        text = journal(MODULE_SERVICES[target]["units"], lines=lines)
    else:
        return f"unknown log target={target!r}\n"
    if mode == "raw":
        return text
    return clean_log_text(text, target)



def read_auth_token(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def parse_cookie(header: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not header:
        return out
    for part in header.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = urllib.parse.unquote(v.strip())
    return out


def redact_url_for_log(text: str) -> str:
    # BaseHTTPRequestHandler passes the raw request line through log_message.
    # Never write dashboard token query values into journald.
    return re.sub(r"([?&]token=)[^&\s]+", r"\1[REDACTED]", text)


INDEX_HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>Agent Bus 黑奴工厂仪表盘</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
:root{--bg:#0f1117;--panel:#171b24;--panel2:#11151d;--text:#d8dee9;--muted:#8b95a7;--ok:#74c476;--bad:#ff6b6b;--warn:#ffd166;--line:#2b3242;--blue:#7aa2f7;}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;font-size:14px}
header{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;background:#0b0e14;position:sticky;top:0;z-index:10}
h1{font-size:18px;margin:0}.muted{color:var(--muted)}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.blue{color:var(--blue)}
nav.tabs{display:flex;gap:6px;padding:10px 12px;background:#0b0e14;border-bottom:1px solid var(--line);position:sticky;top:52px;z-index:9;flex-wrap:wrap}.tabbtn{background:#121722;color:var(--text);border:1px solid var(--line);border-radius:999px;padding:7px 12px}.tabbtn.active{border-color:var(--blue);background:#182133;color:#dbe8ff}.page{display:none;padding:12px}.page.active{display:block}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}.panel h2{font-size:15px;margin:0;padding:10px 12px;border-bottom:1px solid var(--line);background:var(--panel2);display:flex;justify-content:space-between;gap:8px}.body{padding:10px 12px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px}.card{background:#10141d;border:1px solid var(--line);border-radius:8px;padding:8px}.big{font-size:22px;font-weight:700}
table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}th{color:var(--muted);font-weight:500;background:#121722;position:sticky;top:0}.scroll{max-height:62vh;overflow:auto}.log{white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;background:#080b10;color:#b7c0d4;padding:10px;margin:0;max-height:66vh;overflow:auto;border-top:1px solid var(--line);font-size:12px}.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 7px;margin:1px;background:#111824}.pill.ok{border-color:#2f6b3b}.pill.bad{border-color:#833}.pill.warn{border-color:#806a22}button,select{background:#182133;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:5px 8px}button:hover{border-color:var(--blue)}.wide{grid-column:1 / -1}.workers{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:8px}.slot{display:inline-block;width:58px;margin:2px;padding:3px;border-radius:6px;border:1px solid var(--line);text-align:center;background:#10141d}.slot.isolated{background:#2a1518;border-color:#7a3039}.slot.leased{background:#2b2412;border-color:#8a6d20}.notice{border:1px solid #3d4660;background:#10141d;border-radius:8px;padding:8px;margin-bottom:8px}.state{font-weight:700}.small{font-size:12px}.nowrap{white-space:nowrap}.logbar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:8px 12px;border-top:1px solid var(--line);background:#10141d}.health-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px}.module-log{display:none}.module-log.active{display:block}
@media(max-width:1000px){.grid{grid-template-columns:1fr}nav.tabs{top:50px}.health-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header><h1>Agent Bus 黑奴工厂仪表盘 <span class="muted">v0.3.8 tabs / readiness-signal</span></h1><div><span id="stamp" class="muted">loading</span> <button onclick="refreshAll()">刷新</button></div></header>
<nav class="tabs">
  <button class="tabbtn active" data-page="overview" onclick="showPage('overview')">总览</button>
  <button class="tabbtn" data-page="factory" onclick="showPage('factory')">工厂 Runs</button>
  <button class="tabbtn" data-page="workers" onclick="showPage('workers')">黑奴池</button>
  <button class="tabbtn" data-page="bots" onclick="showPage('bots')">Bot 服务</button>
  <button class="tabbtn" data-page="logs" onclick="showPage('logs')">日志</button>
  <button class="tabbtn" data-page="models" onclick="showPage('models'); loadModelConfig()">模型配置</button>
</nav>
<main>
  <section id="page-overview" class="page active"><div class="grid"><section class="panel wide"><h2>总览 <span class="muted">read-only</span></h2><div class="body" id="overview_body"></div></section><section class="panel"><h2>最近 Run</h2><div class="body" id="overview_runs"></div></section><section class="panel"><h2>服务摘要</h2><div class="body" id="overview_health"></div></section></div></section>
  <section id="page-factory" class="page"><div class="grid"><section class="panel wide"><h2>黑奴工厂状态 <span id="factory_latest" class="muted"></span></h2><div class="body" id="factory_body"></div><div class="logbar"><button onclick="loadLog('factory')">工厂日志</button><button onclick="showPage('logs')">去日志页</button><span class="muted">自动刷新 5s</span></div></section><section class="panel wide"><h2>Run 详情 <span id="run_detail_title" class="muted">未选择</span></h2><div class="body" id="run_detail_body"><div class="notice muted">点击 Recent Runs 里的 run 名称查看验尸详情。</div></div></section></div></section>
  <section id="page-workers" class="page"><section class="panel"><h2>黑奴状态 / Worker Pool <span id="worker_sum" class="muted"></span></h2><div class="body workers" id="workers_body"></div><div class="logbar"><button onclick="loadLog('workers')">黑奴状态日志</button><button onclick="showPage('logs')">去日志页</button></div></section></section>
  <section id="page-bots" class="page"><div class="health-grid" id="bots_body"></div></section>
  <section id="page-logs" class="page"><section class="panel"><h2>日志 <span id="log_title" class="muted">factory</span></h2><div class="logbar"><button onclick="loadLog('factory')">工厂</button><button onclick="loadLog('workers')">黑奴池</button><button onclick="loadLog('nonebot')">NoneBot 秧秧</button><button onclick="loadLog('astrbot')">AstrBot 娅娅</button><button onclick="loadLog('astrbot_yangyang')">AstrBot 秧秧</button><button onclick="loadLog('nekro')">Nekro</button><button id="live_log_btn" onclick="toggleLiveLog()">实时滚动：开</button><button id="log_mode_btn" onclick="toggleLogMode()">日志模式：精简</button><span id="live_log_hint" class="muted">每 3s 刷新并滚到底</span></div><pre class="log" id="main_log"></pre></section></section>
  <section id="page-models" class="page"><section class="panel"><h2>模型配置 <span class="muted">env-safe</span></h2><div class="body" id="models_body"><div class="notice muted">loading...</div></div></section></section>
</main>
<script>
let lastData=null; let activePage='overview'; let activeLogTarget='factory'; let logMode='clean'; let liveLog=true; let liveLogTimer=null;
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
function clsState(d){d=String(d||'').toUpperCase(); if(['FREE','IDLE','COLLECTED','CLOSED','ONLINE','HAS_REPORT','HAS_CONTROLLER','VALIDATED_NEED_HUMAN','FORENSIC_DONE'].includes(d))return 'ok'; if(['RUNNING','BUSY','LEASED','DRY_RUN','NEED_REVIEW','NEED_CLOSURE','MANUAL_CLOSED','MANUAL_CLOSURE','STALE_RUNNING','EVENTS_ONLY','ABORTED'].includes(d))return 'warn'; if(['STOPPED','UNKNOWN','NO_MANIFEST','NO_REPORT','NO_CONTROLLER_REPORT','CHECK'].includes(d))return 'blue'; if(['ISOLATED','FACTORY_FAIL'].includes(d))return 'bad'; return 'blue';}
function labelSlotState(s){s=String(s||'').toLowerCase(); if(s==='idle')return '空闲'; if(s==='leased')return '占用'; if(s==='isolated')return '隔离'; return s||'未知';}
async function getJSON(u){let r=await fetch(u,{cache:'no-store'});return await r.json();}
function showPage(name){activePage=name; for(const el of document.querySelectorAll('.page'))el.classList.toggle('active',el.id==='page-'+name); for(const b of document.querySelectorAll('.tabbtn'))b.classList.toggle('active',b.dataset.page===name);}
async function refreshAll(){
  try{lastData=await getJSON('/api/summary'); document.getElementById('stamp').textContent='更新 '+lastData.generated_at; renderAll(lastData);}catch(e){document.getElementById('stamp').textContent='刷新失败 '+e;}
}
function renderAll(data){renderOverview(data); renderFactory(data.factory); renderWorkers(data.workers); renderBots(data.health);}
function renderOverview(data){
  const f=data.factory||{}, latest=f.latest||{}; const w=data.workers||{}, rd=data.readiness||{}; let total=0, leased=0, isolated=0;
  for(const b of Object.values(w.backends||{})){total+=b.stats.total; leased+=b.stats.leased; isolated+=b.stats.isolated;}
  const health=Object.entries(data.health||{}); const online=health.filter(([_,h])=>h.online).length;
  let readinessHtml=`<div class="notice"><b>生产前检查</b>：<span class="state ${clsState(rd.status)}">${esc(rd.status||'UNKNOWN')}</span> <span class="muted">blocking=${esc(rd.blocking_count||0)} warning=${esc(rd.warning_count||0)}</span></div>`;
  for(const issue of rd.issues||[]) readinessHtml+=`<div class="notice bad small"><b>${esc(issue.code)}</b>: ${esc(issue.message)} ${esc((issue.runs||issue.services||[]).join(', '))}</div>`;
  for(const warn of (rd.warnings||[]).slice(0,6)) readinessHtml+=`<div class="notice warn small"><b>${esc(warn.code)}</b>: ${esc(warn.message)} ${esc((warn.runs||warn.services||[]).join(', '))}</div>`;
  document.getElementById('overview_body').innerHTML=`<div class="notice muted">分页面状态板：总览只放摘要；Runs、黑奴池、Bot、日志拆开看。</div>${readinessHtml}<div class="cards"><div class="card"><div class="muted">最近机械态</div><div class="big ${clsState(latest.activity_state)}">${esc(latest.activity_state||'UNKNOWN')}</div><div class="small">${esc(latest.name||'no runs')}</div></div><div class="card"><div class="muted">人工验尸</div><div class="big ${clsState(latest.review_state)}">${esc(latest.review_state||'UNKNOWN')}</div></div><div class="card"><div class="muted">黑奴池</div><div class="big ${isolated?'warn':'ok'}">${total} / ${leased} / ${isolated}</div><div class="small muted">total / leased / isolated</div></div><div class="card"><div class="muted">Bot 在线</div><div class="big ${online===health.length?'ok':'warn'}">${online}/${health.length}</div></div></div>`;
  let rows=''; for(const r of (f.recent_runs||[]).slice(0,6)){rows+=`<tr><td class="nowrap">${esc(r.mtime_text)}</td><td class="small">${esc(r.name)}</td><td class="state ${clsState(r.activity_state)}">${esc(r.activity_state)}</td><td>${esc(r.validation||'')}</td></tr>`;}
  document.getElementById('overview_runs').innerHTML=`<div class="scroll"><table><thead><tr><th>时间</th><th>run</th><th>机械态</th><th>validation</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  let hrows=''; for(const [key,h] of health){hrows+=`<tr><td>${esc(h.title||key)}</td><td class="${h.online?'ok':'bad'}">${h.online?'ONLINE':'CHECK'}</td><td>${h.active_count}/${h.total}</td><td class="${h.connection_marker_in_tail?'ok':'warn'}">${h.connection_marker_in_tail?'YES':'UNKNOWN'} <span class="small muted">${esc(h.connection_marker_reason||'')}</span></td></tr>`;}
  document.getElementById('overview_health').innerHTML=`<table><thead><tr><th>模块</th><th>状态</th><th>服务</th><th>连接痕迹</th></tr></thead><tbody>${hrows}</tbody></table>`;
}
function renderIsolationDetails(w){
  const isolated=(w.items||[]).filter(x=>x.isolated);
  if(!isolated.length) return '<div class="notice ok">无隔离槽位。</div>';
  let html='<div class="notice warn"><b>隔离槽位</b>：'+isolated.length+' 个。隔离 worker 不会被生产派工选中。</div>';
  html+='<table><thead><tr><th>backend</th><th>worker</th><th>reason</th><th>last run</th><th>last validation</th><th>issues</th></tr></thead><tbody>';
  for(const it of isolated){const iso=it.isolation||{}, last=it.last||{}; const issues=(last.issues||[]).map(x=>x.code||x.message).join(', '); html+=`<tr><td>${esc(it.backend)}</td><td class="state warn">${esc(it.workspace_id)}</td><td class="small">${esc(iso.reason||'')}</td><td class="small"><button class="small" onclick="loadRunDetail('${encodeURIComponent(last.run||'')}')">${esc(last.run||'')}</button></td><td class="${clsState(last.validation_status)}">${esc(last.validation_status||'')}</td><td class="small muted">${esc(issues)}</td></tr>`;}
  html+='</tbody></table>'; return html;
}

function renderFactory(f){
  const latest=f.latest; document.getElementById('factory_latest').textContent=latest?`${latest.name} / ${latest.activity_state||'UNKNOWN'} / ${latest.review_state||'UNKNOWN'}`:'no runs';
  let html=`<div class="notice muted">L2.999 状态板：只显示机械事实；已识别 manual_closure / ABORTED / stale running。PASS/FAIL 不代表最终验收。</div>`;
  html+=`<div class="cards"><div class="card"><div class="muted">Run Root</div><div class="small">${esc(f.run_root)}</div></div><div class="card"><div class="muted">隔离槽位</div><div class="big ${f.active_isolated_count?'warn':'ok'}">${f.active_isolated_count}</div></div><div class="card"><div class="muted">最近机械态</div><div class="big ${clsState(latest&&latest.activity_state)}">${esc(latest&&latest.activity_state||'UNKNOWN')}</div></div><div class="card"><div class="muted">人工验尸队列</div><div class="big ${clsState(latest&&latest.review_state)}">${esc(latest&&latest.review_state||'UNKNOWN')}</div></div></div>`;
  html+=`<h3>Recent Runs</h3><div class="scroll"><table><thead><tr><th>时间</th><th>run</th><th>backend</th><th>机械态</th><th>人工验尸</th><th>产物</th><th>报告</th><th>validation</th><th>pool</th><th>标记</th></tr></thead><tbody>`;
  for(const r of f.recent_runs||[]){html+=`<tr><td class="nowrap">${esc(r.mtime_text)}</td><td class="small"><button class="small" onclick="loadRunDetail('${encodeURIComponent(r.name)}')">${esc(r.name)}</button></td><td>${esc(r.backend)}</td><td class="state ${clsState(r.activity_state)}">${esc(r.activity_state||'UNKNOWN')}</td><td class="state ${clsState(r.review_state)}">${esc(r.review_state||'UNKNOWN')}</td><td class="${clsState(r.artifact_state)}">${esc(r.artifact_state||'')}</td><td class="${clsState(r.report_state)}">${esc(r.report_state||'')}</td><td>${esc(r.validation||'')}</td><td>${esc(r.pool_size)}</td><td class="small muted">${esc((r.markers||[]).slice(0,5).join(' | '))}</td></tr>`;}
  html+=`</tbody></table></div>`; document.getElementById('factory_body').innerHTML=html;
}
function renderWorkers(w){
  let total=0, leased=0, isolated=0; let html='';
  for(const [bk,b] of Object.entries(w.backends||{})){const st=b.stats; total+=st.total; leased+=st.leased; isolated+=st.isolated; html+=`<div class="card"><div><b>${esc(b.meta.label)}</b> <span class="muted">${esc(bk)}</span></div><div class="small muted">total=${st.total} idle=${st.idle} leased=${st.leased} isolated=${st.isolated} unknown=${st.unknown}</div><div>`;
    for(const it of b.items){let c='slot'; if(it.state==='isolated')c+=' isolated'; if(it.state==='leased')c+=' leased'; let reaped=it.last&&it.last.watchdog_reaped; let title=`${it.workspace_id} state=${it.state}\nlast_run=${(it.last&&it.last.run)||'none'} ${reaped?'watchdog_reaped='+it.last.watchdog_reap_reason:''}`; html+=`<span class="${c}" title="${esc(title)}">${esc(it.workspace_id)}<br><span class="small">${esc(labelSlotState(it.state))}${reaped?' 🪦':''}</span></span>`;}
    html+='</div></div>';
  }
  html='<div class="wide">'+renderIsolationDetails(w)+'</div>'+html;
  document.getElementById('worker_sum').textContent=`total=${total} leased=${leased} isolated=${isolated}`; document.getElementById('workers_body').innerHTML=html;
}
function renderBots(health){
  let html='';
  for(const [key,h] of Object.entries(health||{})){html+=`<section class="panel"><h2>${esc(h.title||key)} <span><span class="pill ${h.online?'ok':'bad'}">${h.active_count}/${h.total} active</span></span></h2><div class="body">`;
    html+=`<div class="cards"><div class="card"><div class="muted">整体</div><div class="big ${h.online?'ok':'bad'}">${h.online?'ONLINE':'CHECK'}</div></div><div class="card"><div class="muted">连接痕迹</div><div class="big ${h.connection_marker_in_tail?'ok':'warn'}">${h.connection_marker_in_tail?'YES':'UNKNOWN'}</div><div class="small muted">${esc(h.connection_marker_reason||'')}</div></div></div>`;
    html+='<table><thead><tr><th>unit</th><th>active</th><th>sub</th><th>pid</th><th>restarts</th></tr></thead><tbody>';
    for(const s of h.services||[]){html+=`<tr><td>${esc(s.unit)}</td><td class="${s.active?'ok':'bad'}">${esc(s.ActiveState)}</td><td>${esc(s.SubState)}</td><td>${esc(s.MainPID)}</td><td>${esc(s.NRestarts)}</td></tr>`;}
    html+=`</tbody></table></div><div class="logbar"><button onclick="loadLog('${esc(key)}')">查看日志</button><button onclick="showPage('logs')">去日志页</button></div></section>`;
  }
  document.getElementById('bots_body').innerHTML=html;
}
async function fetchLog(target,{showLoading=false,forceScroll=false}={}){
  const pre=document.getElementById('main_log'); document.getElementById('log_title').textContent=target;
  if(showLoading) pre.textContent='loading '+target+'...';
  try{
    let r=await fetch('/api/logs?target='+encodeURIComponent(target)+'&lines=300&mode='+encodeURIComponent(logMode),{cache:'no-store'});
    const text=await r.text();
    const wasNearBottom=(pre.scrollHeight-pre.scrollTop-pre.clientHeight)<32;
    pre.textContent=text;
    if(forceScroll || (liveLog && wasNearBottom)) pre.scrollTop=pre.scrollHeight;
  }catch(e){pre.textContent='log error '+e;}
}
async function loadLog(target){activeLogTarget=target; showPage('logs'); await fetchLog(target,{showLoading:true,forceScroll:true});}
function updateLiveLogButton(){
  const btn=document.getElementById('live_log_btn'); const hint=document.getElementById('live_log_hint'); const modeBtn=document.getElementById('log_mode_btn');
  if(btn) btn.textContent='实时滚动：'+(liveLog?'开':'关');
  if(modeBtn) modeBtn.textContent='日志模式：'+(logMode==='clean'?'精简':'原始');
  if(hint) hint.textContent=liveLog?'每 3s 刷新并滚到底':'已暂停自动刷新，可自由回看';
}
function startLiveLogTimer(){
  if(liveLogTimer) clearInterval(liveLogTimer);
  liveLogTimer=setInterval(()=>{ if(liveLog && activePage==='logs') fetchLog(activeLogTarget,{forceScroll:true}); },3000);
}
function toggleLiveLog(){liveLog=!liveLog; updateLiveLogButton(); if(liveLog) fetchLog(activeLogTarget,{forceScroll:true});}
function toggleLogMode(){logMode=(logMode==='clean')?'raw':'clean'; updateLiveLogButton(); fetchLog(activeLogTarget,{showLoading:true,forceScroll:true});}

async function loadModelConfig(){
  const body=document.getElementById('models_body'); if(!body)return;
  body.innerHTML='<div class="notice muted">loading model config...</div>';
  try{renderModelConfig(await getJSON('/api/model_config'));}catch(e){body.innerHTML='<div class="notice bad">模型配置读取失败 '+esc(e)+'</div>';}
}
function renderModelConfig(cfg){
  const body=document.getElementById('models_body'); if(!body)return;
  const opts=(cfg.profiles||[]).map(p=>`<option value="${esc(p.id)}">${esc(p.label)} / ${esc(p.id)}</option>`).join('');
  let html=`<div class="notice"><b>I叔模型</b>：<span class="state ok">${esc(cfg.isaac_model_profile)}</span> <span class="muted">私聊=${esc(cfg.private_profile)} 群聊=${esc(cfg.group_profile)}</span><br><span class="small muted">${esc(cfg.runtime_config)}</span></div>`;
  html+=`<div class="logbar"><label>scope <select id="model_scope"><option value="isaac">I叔 only</option><option value="private">私聊全局</option><option value="group">群聊全局</option></select></label><label>profile <select id="model_profile">${opts}</select></label><button onclick="applyModelConfig()">应用切换</button><span class="muted">不显示/保存密钥；只使用 env var 名称。</span></div>`;
  html+='<table><thead><tr><th>profile</th><th>provider</th><th>model</th><th>enabled</th><th>api env</th><th>base env</th></tr></thead><tbody>';
  for(const p of cfg.profiles||[]){html+=`<tr><td><b>${esc(p.label)}</b><br><span class="small muted">${esc(p.id)}</span></td><td>${esc(p.provider)}</td><td>${esc(p.model)}</td><td class="${p.enabled?'ok':'warn'}">${p.enabled?'true':'false'}</td><td class="${p.api_key_env_set?'ok':'bad'}">${esc(p.api_key_env||'-')} set=${p.api_key_env_set?'yes':'no'}</td><td class="${p.base_url_env_set?'ok':'bad'}">${esc(p.base_url_env||'-')} set=${p.base_url_env_set?'yes':'no'}</td></tr>`;}
  html+='</tbody></table>';
  html+=`<div class="notice warn small">切换后通常需要重启 <code>yangyang-nonebot.service</code> 才会让长驻 router/agent 拿到新配置；WebUI 当前只做配置写入，不展示密钥值。</div>`;
  body.innerHTML=html;
  const sel=document.getElementById('model_profile'); if(sel) sel.value=cfg.isaac_model_profile||'v4_pro';
}
async function applyModelConfig(){
  const scope=document.getElementById('model_scope').value; const profile=document.getElementById('model_profile').value;
  const r=await fetch('/api/model_config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope,profile})});
  const data=await r.json();
  if(!data.ok){alert('切换失败: '+(data.error||'unknown')); return;}
  renderModelConfig(data);
}
refreshAll(); loadLog('factory'); updateLiveLogButton(); startLiveLogTimer(); setInterval(refreshAll,5000);
</script>
</body>
</html>
"""


LOGIN_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Agent Bus WebUI 登录</title>
<style>body{background:#0f1117;color:#d8dee9;font-family:system-ui,sans-serif;margin:0;display:grid;place-items:center;height:100vh}.box{background:#171b24;border:1px solid #2b3242;border-radius:12px;padding:24px;min-width:320px}input{width:100%;padding:8px;background:#10141d;color:#d8dee9;border:1px solid #2b3242;border-radius:8px}button{margin-top:10px;padding:8px 12px;background:#182133;color:#d8dee9;border:1px solid #2b3242;border-radius:8px}</style></head>
<body><form class="box" method="get"><h2>Agent Bus WebUI</h2><p>输入访问 token。</p><input name="token" autocomplete="off" autofocus><button type="submit">进入</button></form></body></html>"""


def safe_run_dir_from_name(name: str) -> Path | None:
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        return None
    rd = (RUN_ROOT / name).resolve()
    try:
        rd.relative_to(RUN_ROOT.resolve())
    except ValueError:
        return None
    if not rd.is_dir():
        return None
    return rd


def safe_artifact_preview(run_name: str, rel_path: str, max_chars: int = 20000) -> dict[str, Any]:
    rd = safe_run_dir_from_name(run_name)
    if rd is None:
        return {"error": "run not found"}
    if not rel_path or rel_path.startswith("/") or ".." in Path(rel_path).parts:
        return {"error": "invalid path"}
    path = (rd / rel_path).resolve()
    try:
        path.relative_to(rd)
    except ValueError:
        return {"error": "path outside run"}
    if not path.is_file():
        return {"error": "artifact not found", "path": str(path)}
    size = path.stat().st_size
    data = path.read_bytes()[: max(1, max_chars)]
    text = data.decode("utf-8", errors="replace")
    return {
        "run": run_name,
        "relative_path": rel_path,
        "path": str(path),
        "bytes": size,
        "truncated": size > len(data),
        "text": text,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentBusFactoryWebUI/0.3.8"

    def log_message(self, fmt: str, *args: Any) -> None:
        try:
            msg = fmt % args
        except Exception:
            msg = fmt
        sys.stderr.write("[%s] %s\n" % (fmt_ts(now_ts()), redact_url_for_log(msg)))

    @property
    def auth_token(self) -> str:
        return getattr(self.server, "auth_token", "")  # type: ignore[attr-defined]

    def request_authorized(self, parsed: urllib.parse.ParseResult, qs: dict[str, list[str]]) -> tuple[bool, bool]:
        token = self.auth_token
        if not token:
            return True, False
        query_token = (qs.get("token") or [""])[0]
        if query_token and hmac.compare_digest(query_token, token):
            return True, True
        cookies = parse_cookie(self.headers.get("Cookie"))
        cookie_token = cookies.get("agentbus_token", "")
        if cookie_token and hmac.compare_digest(cookie_token, token):
            return True, False
        return False, False

    def send_bytes(self, body: bytes, content_type: str = "application/octet-stream", status: int = 200, set_cookie: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if set_cookie and self.auth_token:
            self.send_header("Set-Cookie", "agentbus_token=" + urllib.parse.quote(self.auth_token) + "; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj: Any, status: int = 200) -> None:
        self.send_bytes(json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8", status)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"
        authorized, should_set_cookie = self.request_authorized(parsed, qs)
        if not authorized:
            return self.send_json({"error": "unauthorized"}, 401)
        try:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(min(length, 65536)) if length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
            if path == "/api/model_config":
                return self.send_json(apply_model_config(payload))
            return self.send_json({"error": "not_found"}, 404)
        except Exception as e:
            return self.send_json({"error": repr(e)}, 500)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"
        authorized, should_set_cookie = self.request_authorized(parsed, qs)
        if not authorized:
            if path == "/":
                return self.send_bytes(LOGIN_HTML.encode("utf-8"), "text/html; charset=utf-8", 401)
            return self.send_json({"error": "unauthorized"}, 401)
        try:
            if path == "/":
                return self.send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8", set_cookie=should_set_cookie)
            if path == "/api/summary":
                return self.send_json(full_summary())
            if path == "/api/factory":
                limit = int((qs.get("limit") or [24])[0])
                return self.send_json(factory_summary(limit=max(1, min(limit, 100))))
            if path == "/api/workers":
                return self.send_json(worker_pool_status())
            if path == "/api/readiness":
                return self.send_json(factory_readiness())
            if path == "/api/health":
                return self.send_json(module_health())
            if path == "/api/model_config":
                return self.send_json(model_config_summary())
            if path == "/api/logs":
                target = (qs.get("target") or ["factory"])[0]
                lines = int((qs.get("lines") or [200])[0])
                mode = (qs.get("mode") or ["clean"])[0]
                if mode not in {"clean", "raw"}:
                    mode = "clean"
                if target not in LOG_TARGETS:
                    return self.send_bytes(f"unknown target={target}\n".encode("utf-8"), "text/plain; charset=utf-8", 404)
                return self.send_bytes(log_target(target, lines=max(1, min(lines, 2000)), mode=mode).encode("utf-8"), "text/plain; charset=utf-8")
            if path == "/api/artifact":
                name = (qs.get("run") or [""])[0]
                rel_path = (qs.get("path") or [""])[0]
                preview = safe_artifact_preview(name, rel_path)
                return self.send_json(preview, 404 if preview.get("error") else 200)
            if path == "/api/run":
                name = (qs.get("name") or [""])[0]
                rd = safe_run_dir_from_name(name)
                if rd is None:
                    return self.send_json({"error": "run not found"}, 404)
                return self.send_json({
                    "summary": summarize_run(rd),
                    "controller_report": read_json(rd / "controller_report.json"),
                    "dispatcher_status": read_json(rd / "dispatcher_status.json"),
                    "validation_report": read_first_json([rd / "validation_report.json", rd / "write_artifacts" / "validation_report.json", rd / "pure_offline_validation_report.json"]),
                    "manifest": read_first_json([rd / "manifest.json", rd / "write_artifacts" / "manifest.json", rd / "pure_offline_manifest.json"]),
                    "write_artifacts_manifest": read_json(rd / "write_artifacts" / "manifest.json"),
                    "manual_closure_report": read_json(rd / "manual_closure_report.json"),
                    "pure_offline_validation_report": read_json(rd / "pure_offline_validation_report.json"),
                })
            return self.send_bytes(b"not found\n", "text/plain; charset=utf-8", 404)
        except Exception as e:
            return self.send_json({"error": repr(e)}, 500)


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only Agent Bus / bot health WebUI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--token-file", help="If set, require token query/cookie auth using this file")
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.auth_token = read_auth_token(args.token_file)  # type: ignore[attr-defined]
    auth_state = "token-auth" if httpd.auth_token else "no-auth"  # type: ignore[attr-defined]
    print(f"AgentBusFactoryWebUI listening on http://{args.host}:{args.port} ({auth_state})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
