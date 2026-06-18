"""Isaac P0 workspace_report: read-only minimal workspace overview.

Hard rules:
- No shell, no executor, no network.
- Never reads env/key/token/base_url/secret content.
- Returns a short dict; caller formats the reply.
- Fails soft: missing/unreadable -> "unknown".
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

# Derive project root from this file so the report follows deployments where
# /opt/yangyang_nonebot is a symlink or the project is mounted elsewhere.
# parents: core -> yangyang -> plugins -> src -> <project_root>
PROJECT_ROOT = Path(__file__).resolve().parents[4]

_SKIP_DIR_NAMES = {"__pycache__", ".git", ".venv", "venv", "node_modules"}
_SKIP_FILE_PATTERNS = (
    re.compile(r"\.pyc$"),
    re.compile(r"\.pyo$"),
    re.compile(r"\.env$"),
    re.compile(r"\.env\..+$"),
    re.compile(r"id_rsa", re.IGNORECASE),
    re.compile(r"\.pem$"),
    re.compile(r"\.key$"),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"memory[._-]?(store|body|raw)"),
)
_RECENT_LIMIT = 10

_AUDIT_REL = Path("data/audit/isaac_p0_audit.jsonl")


def _safe_exists(rel: str) -> str:
    try:
        p = PROJECT_ROOT / rel
        return "present" if p.is_dir() else "missing"
    except Exception:
        return "unknown"


def _audit_status() -> dict[str, Any]:
    out: dict[str, Any] = {"exists": "unknown", "line_count": "unknown", "size_bytes": "unknown"}
    try:
        p = PROJECT_ROOT / _AUDIT_REL
        if not p.is_file():
            out["exists"] = "missing"
            return out
        out["exists"] = "present"
        try:
            out["size_bytes"] = int(p.stat().st_size)
        except Exception:
            out["size_bytes"] = "unknown"
        try:
            with p.open("rb") as fh:
                buf = fh.read(min(out["size_bytes"] if isinstance(out["size_bytes"], int) else 65536, 65536))
            out["line_count"] = buf.count(b"\n")
            if buf and not buf.endswith(b"\n"):
                out["line_count"] = int(out["line_count"]) + 1
        except Exception:
            out["line_count"] = "unknown"
    except Exception:
        return out
    return out


def _recent_files() -> list[str]:
    out: list[str] = []
    try:
        root = PROJECT_ROOT
        if not root.is_dir():
            return out
        candidates: list[tuple[float, str]] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
            for fn in filenames:
                if any(pat.search(fn) for pat in _SKIP_FILE_PATTERNS):
                    continue
                full = Path(dirpath) / fn
                try:
                    st = full.stat()
                except Exception:
                    continue
                if full.resolve() == Path(__file__).resolve():
                    continue
                try:
                    rel = str(full.relative_to(root))
                except Exception:
                    continue
                if rel.startswith("data/audit/") or "/.audit/" in rel:
                    continue
                rel_path = rel.replace("\\", "/")
                if any(frag in rel_path for frag in (
                    "/opt",
                    "src/plugins/yangyang/data",
                    ".env",
                    "runtime_config",
                    "project_notes",
                    "long_term/memories.jsonl",
                )):
                    continue
                candidates.append((st.st_mtime, rel_path))
        candidates.sort(key=lambda x: x[0], reverse=True)
        for _, rel in candidates[:_RECENT_LIMIT]:
            out.append(rel)
    except Exception:
        return out
    return out


def build_workspace_report() -> dict[str, Any]:
    # NOTE: dict enters Agent Bus payload.  Do NOT include absolute paths
    # containing FORBIDDEN_PAYLOAD_FRAGMENTS substrings (e.g. "/opt").
    # The reply formatter reconstructs the human-readable path locally.
    return {
        "schema_version": "i_line.p0.workspace_report.v1",
        "project_name": PROJECT_ROOT.name,
        "directories": {
            "src/plugins/yangyang": _safe_exists("src/plugins/yangyang"),
            "tests": _safe_exists("tests"),
            "data/audit": _safe_exists("data/audit"),
            "backups": _safe_exists("backups"),
        },
        "audit": _audit_status(),
        "recent_files": _recent_files(),
    }


def format_workspace_report(report: Mapping[str, Any]) -> str:
    try:
        dirs = dict(report.get("directories") or {})
        audit = dict(report.get("audit") or {})
        recent = list(report.get("recent_files") or [])
        project_name = str(report.get("project_name") or PROJECT_ROOT.name)
        parts = [
            "I叔 P0 workspace_report（只读最小实用版）",
            f"project_name={project_name} project_root=/<fixed-runtime-root>/{project_name}",
            "dirs: "
            + " ".join(f"{k}={v}" for k, v in dirs.items()),
            f"audit: isaac_p0_audit.jsonl exists={audit.get('exists','unknown')} "
            f"line_count={audit.get('line_count','unknown')} "
            f"size_bytes={audit.get('size_bytes','unknown')}",
        ]
        if recent:
            parts.append("recent_files: " + " | ".join(recent))
        else:
            parts.append("recent_files: none")
        return "\n".join(parts)
    except Exception:
        return "I叔 P0 workspace_report: unknown (formatter failed)"
