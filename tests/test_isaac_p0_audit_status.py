"""Isaac P0 audit / status read-only report tests.

Fail-soft behaviour, owner-private gating, no sensitive markers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import json
from pathlib import Path
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang"


def _load(mod_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


isaac_bus = _load(
    "isaac_agent_bus_p0_under_test",
    PLUGIN_ROOT / "core" / "isaac_agent_bus_p0.py",
)
isaac_audit = _load(
    "isaac_audit_report_under_test",
    PLUGIN_ROOT / "core" / "isaac_audit_report.py",
)
handle_isaac_agent_bus_p0_message = isaac_bus.handle_isaac_agent_bus_p0_message


SENSITIVE_MARKERS = (
    "api_key", "apikey", "token", "base_url", "secret", "password",
    "authorization", "cookie", "session_key",
)


@dataclass
class DummyMessage:
    text: str
    channel: str = "private"
    is_owner: bool = True
    raw_content: str = ""
    uid: str = "335059272"
    group_id: str = ""
    msg_id: str = "dummy-msg"
    nick: str = "漂♂总"
    is_at_bot: bool = False
    owner_command: bool = False
    explicit_command: bool = False
    at_user_ids: list[str] = field(default_factory=list)


def _make_record(ts: str, decision: str, trigger: str, cmd: str, task: str, reason: str = "") -> dict:
    return {
        "ts": ts,
        "decision": decision,
        "trigger_type": trigger,
        "command_head": cmd,
        "task_type": task,
        "reason": reason,
        "user_id": "335059272",
    }


def _write_audit(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_owner_private_audit_returns_aggregates_and_recent(monkeypatch, tmp_path) -> None:
    audit_dir = tmp_path / "audit"
    audit_path = audit_dir / "isaac_p0_audit.jsonl"
    records = [
        _make_record("2026-01-01T00:00:00Z", "handled", "slash_fallback", "/i叔", "health_report", "ok"),
        _make_record("2026-01-01T00:00:01Z", "denied", "slash_fallback", "/i叔", "workspace_report", "private_only"),
        _make_record("2026-01-01T00:00:02Z", "handled", "natural_llm", "/i叔", "workspace_report", "ok"),
        _make_record("2026-01-01T00:00:03Z", "ignored", "slash_fallback", "/i叔", "help_report", "noop"),
    ]
    _write_audit(audit_path, records)
    monkeypatch.setattr(isaac_bus, "_resolve_isaac_audit_dir", lambda: audit_dir)
    isaac_audit.build_audit_report.cache_clear() if hasattr(isaac_audit.build_audit_report, "cache_clear") else None

    msg = DummyMessage(text="/i叔 audit")
    result = handle_isaac_agent_bus_p0_message(msg)
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == "audit_report"
    reply = str(result.reply or "")
    assert "audit 概览" in reply
    assert "decision_counts" in reply
    assert "handled=1" in reply or "handled=" in reply
    assert "slash_fallback" in reply
    assert "natural_llm" in reply
    assert "raw_uid" not in reply
    assert "335059272" not in reply  # raw QQ must never appear
    diag = dict((result.worker_result or {}).get("diagnostics") or {})
    report = dict(diag.get("audit_report") or {})
    assert report.get("audit_file_exists") is True
    counts = dict(report.get("counts") or {})
    assert counts.get("decision", {}).get("handled", 0) >= 1
    assert counts.get("decision", {}).get("denied", 0) >= 1
    assert counts.get("decision", {}).get("ignored", 0) >= 1
    assert counts.get("trigger", {}).get("slash_fallback", 0) >= 3
    assert counts.get("trigger", {}).get("natural_llm", 0) >= 1
    recent = list(report.get("recent") or [])
    assert 1 <= len(recent) <= 5
    for r in recent:
        assert "335059272" not in str(r)  # raw QQ never in recent


def test_audit_reply_no_sensitive_markers(monkeypatch, tmp_path) -> None:
    audit_dir = tmp_path / "audit2"
    audit_path = audit_dir / "isaac_p0_audit.jsonl"
    poison = {
        "ts": "2026-02-01T00:00:00Z",
        "decision": "handled",
        "trigger_type": "slash_fallback",
        "command_head": "/i叔",
        "task_type": "health_report",
        "reason": "fake api_key=ABCDEF123 token=bogus secret=zzz",
        "user_id": "335059272",
    }
    _write_audit(audit_path, [poison])
    monkeypatch.setattr(isaac_bus, "_resolve_isaac_audit_dir", lambda: audit_dir)
    msg = DummyMessage(text="/i叔 audit")
    result = handle_isaac_agent_bus_p0_message(msg)
    reply = str(result.reply or "").lower()
    for marker in SENSITIVE_MARKERS:
        assert marker not in reply, f"leaked marker: {marker}"
    assert "abcdef123" not in reply
    assert "bogus" not in reply


def test_audit_missing_file_fail_soft(monkeypatch, tmp_path) -> None:
    empty_dir = tmp_path / "empty_audit"
    empty_dir.mkdir()
    monkeypatch.setattr(isaac_bus, "_resolve_isaac_audit_dir", lambda: empty_dir)
    msg = DummyMessage(text="/i叔 audit")
    result = handle_isaac_agent_bus_p0_message(msg)
    assert result.handled is True
    assert result.allowed is True
    reply = str(result.reply or "")
    assert "audit_file_exists=false" in reply or "audit" in reply.lower()
    assert "total_lines=0" in reply or "EMPTY" in reply


def test_audit_corrupt_jsonl_fail_soft(monkeypatch, tmp_path) -> None:
    bad_dir = tmp_path / "bad_audit"
    bad_dir.mkdir()
    bad_path = bad_dir / "isaac_p0_audit.jsonl"
    bad_path.write_text("not json\n{broken\n", encoding="utf-8")
    monkeypatch.setattr(isaac_bus, "_resolve_isaac_audit_dir", lambda: bad_dir)
    msg = DummyMessage(text="/i叔 audit")
    result = handle_isaac_agent_bus_p0_message(msg)
    assert result.handled is True
    assert result.allowed is True
    reply = str(result.reply or "").lower()
    assert "exception" not in reply
    assert "traceback" not in reply


def test_non_owner_group_audit_denied() -> None:
    msg = DummyMessage(text="/i叔 audit", channel="group", is_owner=False, group_id="999999")
    result = handle_isaac_agent_bus_p0_message(msg)
    assert result.handled is True
    assert result.allowed is False
    reply = str(result.reply or "").lower()
    for marker in SENSITIVE_MARKERS:
        assert marker not in reply
    assert "decision_counts" not in reply
    assert "audit_file_exists" not in reply


def test_status_includes_capabilities() -> None:
    msg = DummyMessage(text="/i叔 status")
    result = handle_isaac_agent_bus_p0_message(msg)
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == "status_report"
    reply = str(result.reply or "")
    assert "status" in reply.lower()
    assert "capabilities" in reply
    for cap in ("health", "workspace", "audit", "help"):
        assert cap in reply


def test_isaac_aliases_audit_and_status() -> None:
    for text in ("/I叔 audit", "/艾萨克 audit", "/i叔 status"):
        msg = DummyMessage(text=text)
        result = handle_isaac_agent_bus_p0_message(msg)
        assert result.handled is True
        assert result.allowed is True, f"failed for {text}: {result.reason}"


def test_old_slash_fallback_workspace_health_help_unchanged() -> None:
    for text, expected_type in (
        ("/i叔 workspace", "workspace_report"),
        ("/I叔 health", "health_report"),
        ("/艾萨克 help", "help_report"),
    ):
        msg = DummyMessage(text=text)
        result = handle_isaac_agent_bus_p0_message(msg)
        assert result.handled is True
        assert result.allowed is True
        assert result.task_type == expected_type, f"{text} -> {result.task_type}"
