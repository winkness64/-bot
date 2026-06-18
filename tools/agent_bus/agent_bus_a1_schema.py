#!/usr/bin/env python3
"""Agent Bus A1.1 schema validator.

Workspace-only, dependency-free schema validation for redacted Agent Bus A1.1
message envelopes.  This module intentionally does not dereference payload
references, read host/runtime files, connect to a bus, call providers/network,
or touch production memory.  Digest matching is limited to optional in-message
``payload_inline_redacted`` synthetic JSON values supplied by fixtures.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

SCHEMA_VERSION = "agent_bus.envelope.a1_1.schema_validation.20260606"
RELEASE_DECISION = "A1_1_SCHEMA_VALIDATION_ONLY_NOT_RUNTIME"

REQUIRED_ENVELOPE_FIELDS = (
    "message_id",
    "message_type",
    "correlation_id",
    "parent_message_id",
    "trace_id",
    "source_agent",
    "target_agent",
    "actor_context",
    "session_scope",
    "risk_level",
    "capability_requested",
    "payload_ref",
    "payload_digest",
    "created_at",
    "ttl_seconds",
    "requires_owner_approval",
    "requires_second_factor",
    "loop_guard",
)

MESSAGE_TYPES = {
    "task_request",
    "task_status",
    "task_result",
    "audit_event",
    "stop_signal",
    "heartbeat",
    "review_request",
    "memory_read_request",
    "memory_write_request",
    "delivery_request",
}

NO_PAYLOAD_MESSAGE_TYPES = {
    "heartbeat",
    "stop_signal",
    "task_status",
    "audit_event",
}

RISK_LEVELS = {"low", "medium", "high", "critical"}

CAPABILITIES = {
    "none",
    "dry_run_plan",
    "dry_run_review",
    "dry_run_audit",
    "audit_append",
    "stop_trace",
    "memory_read",
    "memory_write",
    "delivery_external",
    "external_delivery",
    "system",
    "shell",
    "deploy",
    "write_config",
    "restart",
    "provider",
    "network",
    "production_memory",
    "host_access",
    "executor",
    "tool_execution_reserved",
}

ACTOR_TYPES = {"owner", "agent", "scheduler", "group_user", "system_stub", "unknown"}
ACTOR_CHANNELS = {"internal_bus", "test_fixture", "owner_private", "group_chat", "scheduler", "service_stub"}
SOURCE_TRUST = {"owner_verified", "trusted_agent", "service_stub", "test_fixture", "untrusted_group", "untrusted_context", "unknown"}

SESSION_SCOPE_TYPES = {"private_user", "group", "session", "internal", "engineering_workspace", "group_context"}
SESSION_VISIBILITY = {"internal_only", "owner_private", "group_redacted", "audit_metadata_only", "fixture_only"}
GROUP_VISIBILITY = {"group_redacted", "internal_only", "audit_metadata_only"}

REPLY_POLICIES = {"none", "status_only", "result_once", "review_only", "manual_only", "audit_only"}

PAYLOAD_REF_PREFIXES = ("fixture://", "bus://", "inline_redacted://")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SLUG_RE = re.compile(r"^[a-z][a-z0-9_.:-]{2,127}$")
RAW_NUMERIC_RE = re.compile(r"^\d{6,}$")
LONG_DIGIT_RUN_RE = re.compile(r"\d{6,}")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b", re.IGNORECASE)
PRIVATE_KEY_RE = re.compile(r"BEGIN\s+(?:[A-Z]+\s+)?PRIVATE\s+KEY", re.IGNORECASE)
API_KEY_VALUE_RE = re.compile(r"\bapi[_-]?key\b\s*[:=]", re.IGNORECASE)
TOKEN_VALUE_RE = re.compile(r"\btoken[_-]?value\b", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(r"\bsecret\b", re.IGNORECASE)

SENSITIVE_KEY_MARKERS = (
    "token_value",
    "access_token",
    "refresh_token",
    "api_key",
    "private_key",
    "secret",
    "password",
    "credential",
    "session_cookie",
    "approval_challenge",
    "second_factor_code",
    "mfa_code",
)

SENSITIVE_VALUE_PATTERNS = (
    PRIVATE_KEY_RE,
    BEARER_RE,
    API_KEY_VALUE_RE,
    TOKEN_VALUE_RE,
)

FORBIDDEN_PAYLOAD_FRAGMENTS = (
    "/opt",
    "project_notes",
    "src/plugins/yangyang/data",
    "runtime_config.json",
    "runtime_config",
    ".env",
    "long_term/memories.jsonl",
)

FORBIDDEN_METADATA_FRAGMENTS = FORBIDDEN_PAYLOAD_FRAGMENTS

JSON_PRIMITIVE_TYPES = (str, int, float, bool, type(None))


def stable_json(data: Any) -> str:
    """Return deterministic JSON for synthetic fixture payload hashing only."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_payload(data: Any) -> str:
    """Hash an already-supplied synthetic JSON value; never dereference refs."""
    return "sha256:" + hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()


def _error(failure_class: str, field_path: str, reason: str) -> Dict[str, Any]:
    return {
        "failure_class": failure_class,
        "field_path": field_path,
        "reason": reason,
        "redacted": True,
        "retryable": False,
    }


def _result(
    *,
    valid: bool,
    failure_class: Optional[str] = None,
    field_path: Optional[str] = None,
    reason: Optional[str] = None,
    normalized: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    if not valid:
        errors.append(_error(str(failure_class), str(field_path or "message"), str(reason or failure_class)))
    result: Dict[str, Any] = {
        "valid": valid,
        "failure_class": failure_class,
        "reason": reason,
        "errors": errors,
        "schema_version": SCHEMA_VERSION,
        "release_decision": RELEASE_DECISION,
        "verdict": "PASS" if valid else "BLOCKED",
        "safe_to_route_in_memory": bool(valid),
    }
    if valid and normalized is not None:
        result["normalized"] = dict(normalized)
    return result


def _fail(failure_class: str, field_path: str, reason: str) -> Dict[str, Any]:
    return _result(valid=False, failure_class=failure_class, field_path=field_path, reason=reason)


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_json_value(value: Any) -> bool:
    if isinstance(value, JSON_PRIMITIVE_TYPES):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(child) for key, child in value.items())
    return False


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def _coerce_now(now: Optional[datetime | str]) -> Tuple[Optional[datetime], Optional[str]]:
    if now is None:
        return datetime.now(timezone.utc), None
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return None, "now must include timezone"
        return now.astimezone(timezone.utc), None
    if isinstance(now, str):
        parsed = _parse_iso_datetime(now)
        if parsed is None:
            return None, "now must be an ISO datetime with timezone"
        return parsed, None
    return None, "now must be a datetime or ISO datetime string"


def _safe_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text != value or not (3 <= len(text) <= 128):
        return False
    lowered = text.lower()
    if text != lowered:
        return False
    if RAW_NUMERIC_RE.fullmatch(text) or EMAIL_RE.fullmatch(text):
        return False
    if "/" in text or "\\" in text or " " in text or ".." in text or "~" in text:
        return False
    if "real_user" in lowered or "raw_user" in lowered or "raw_group" in lowered:
        return False
    return bool(UUID_RE.fullmatch(text) or SLUG_RE.fullmatch(text))


def _safe_redacted_id(value: Any, *, allow_agent_id: bool = False, allow_internal_id: bool = False) -> bool:
    if not _safe_id(value):
        return False
    text = str(value)
    if LONG_DIGIT_RUN_RE.search(text):
        return False
    if allow_agent_id and text.startswith(("agent_", "service_", "scheduler_", "yangyang_mock", "yaya_mock", "isaac_mock", "memory_service_stub")):
        return True
    if allow_internal_id and text.startswith(("internal_", "yangyang_nonebot_mvp_redacted")):
        return True
    return "redacted" in text


def _safe_agent_id(value: Any) -> bool:
    return _safe_id(value) and not LONG_DIGIT_RUN_RE.search(str(value))


def _payload_ref_forbidden(value: str) -> bool:
    text = value.strip()
    lowered = text.lower()
    if text != value or not (1 <= len(text) <= 512):
        return True
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in text):
        return True
    if text.startswith("/") or WINDOWS_ABSOLUTE_RE.match(text):
        return True
    if text.startswith(("~", "\\\\")) or "\\" in text:
        return True
    if ".." in text or "%2e" in lowered or "%2f" in lowered or "%5c" in lowered:
        return True
    if not text.startswith(PAYLOAD_REF_PREFIXES):
        return True
    if any(fragment in lowered for fragment in FORBIDDEN_PAYLOAD_FRAGMENTS):
        return True
    if lowered.startswith(("file://", "http://", "https://", "ssh://", "s3://")):
        return True
    return False


def _sensitive_string(value: str) -> bool:
    lowered = value.lower()
    if any(fragment in lowered for fragment in FORBIDDEN_METADATA_FRAGMENTS):
        return True
    if any(marker in lowered for marker in ("token_value", "access_token", "refresh_token", "api_key", "private_key")):
        return True
    if any(pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS):
        return True
    # Keep the plain word "secret" as a hard value marker, but avoid blocking
    # unrelated words such as "secretary".
    if SECRET_VALUE_RE.search(value):
        return True
    return False


def _scan_sensitive(value: Any, path: str = "message") -> Optional[Tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            child_path = f"{path}.{key_text}"
            if any(marker in key_lower for marker in SENSITIVE_KEY_MARKERS):
                return child_path, "forbidden sensitive key marker detected"
            if _sensitive_string(key_text):
                return child_path, "forbidden sensitive key content detected"
            found = _scan_sensitive(child, child_path)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _scan_sensitive(child, f"{path}[{index}]")
            if found:
                return found
    elif isinstance(value, str):
        if _sensitive_string(value):
            return path, "forbidden sensitive value marker detected"
    return None


def _require_nested_fields(obj: Mapping[str, Any], required: Tuple[str, ...], prefix: str, failure_class: str) -> Optional[Dict[str, Any]]:
    for field in required:
        if field not in obj:
            return _fail(failure_class, f"{prefix}.{field}", "required nested field is missing")
    return None


def _validate_actor_context(actor: Mapping[str, Any], envelope: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    if "actor_id_redacted" not in actor and "actor_id" in actor:
        actor = dict(actor)
        actor["actor_id_redacted"] = actor.get("actor_id")
    if "channel" not in actor and "source_channel" in actor:
        actor = dict(actor)
        actor["channel"] = actor.get("source_channel")
    if "source_trust" not in actor and "trust_level" in actor:
        actor = dict(actor)
        actor["source_trust"] = actor.get("trust_level")

    required = ("actor_type", "actor_id_redacted", "channel", "owner_verified", "source_trust")
    missing = _require_nested_fields(actor, required, "envelope.actor_context", "schema_bad_actor_context")
    if missing:
        return missing

    if not isinstance(actor.get("actor_type"), str) or actor.get("actor_type") not in ACTOR_TYPES:
        return _fail("schema_bad_actor_context", "envelope.actor_context.actor_type", "actor_type is not allowed")
    if not isinstance(actor.get("actor_id_redacted"), str) or not _safe_redacted_id(actor.get("actor_id_redacted"), allow_agent_id=True):
        return _fail("schema_bad_actor_context", "envelope.actor_context.actor_id_redacted", "actor id must be safe and redacted")
    if not isinstance(actor.get("channel"), str) or actor.get("channel") not in ACTOR_CHANNELS:
        return _fail("schema_bad_actor_context", "envelope.actor_context.channel", "channel is not allowed")
    if not _is_bool(actor.get("owner_verified")):
        return _fail("schema_type_error", "envelope.actor_context.owner_verified", "owner_verified must be boolean")
    if not isinstance(actor.get("source_trust"), str) or actor.get("source_trust") not in SOURCE_TRUST:
        return _fail("schema_bad_actor_context", "envelope.actor_context.source_trust", "source_trust is not allowed")

    group_id = actor.get("group_id_redacted")
    if group_id is not None and (not isinstance(group_id, str) or not _safe_redacted_id(group_id)):
        return _fail("schema_bad_actor_context", "envelope.actor_context.group_id_redacted", "group id must be redacted")
    if actor.get("channel") == "group_chat" and not group_id:
        return _fail("schema_bad_actor_context", "envelope.actor_context.group_id_redacted", "group_chat requires a redacted group id")
    if actor.get("owner_verified") is True:
        if not (actor.get("actor_type") == "owner" and actor.get("channel") == "owner_private"):
            return _fail("schema_bad_actor_context", "envelope.actor_context.owner_verified", "owner verification is invalid for this actor/channel")
    if actor.get("source_trust") == "owner_verified" and actor.get("owner_verified") is not True:
        return _fail("schema_bad_actor_context", "envelope.actor_context.source_trust", "owner_verified trust requires owner verification")
    if actor.get("source_trust") in {"untrusted_group", "untrusted_context"}:
        if str(envelope.get("capability_requested")) not in {"none", "dry_run_plan", "dry_run_review", "dry_run_audit", "system", "shell", "deploy", "write_config", "restart", "provider", "network", "production_memory", "host_access", "executor", "tool_execution_reserved"}:
            return _fail("schema_bad_actor_context", "envelope.actor_context.source_trust", "untrusted group scope cannot request elevated capability")
    return None


def _validate_session_scope(scope: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    if "scope_id_redacted" not in scope and "scope_id" in scope:
        scope = dict(scope)
        scope["scope_id_redacted"] = scope.get("scope_id")
    if "visibility" not in scope:
        scope = dict(scope)
        scope["visibility"] = "group_redacted" if scope.get("scope_type") in {"group", "group_context"} else "internal_only"

    required = ("scope_type", "scope_id_redacted", "visibility")
    missing = _require_nested_fields(scope, required, "envelope.session_scope", "schema_bad_session_scope")
    if missing:
        return missing

    if not isinstance(scope.get("scope_type"), str) or scope.get("scope_type") not in SESSION_SCOPE_TYPES:
        return _fail("schema_bad_session_scope", "envelope.session_scope.scope_type", "scope_type is not allowed")
    if not isinstance(scope.get("scope_id_redacted"), str) or not _safe_redacted_id(scope.get("scope_id_redacted"), allow_internal_id=True):
        return _fail("schema_bad_session_scope", "envelope.session_scope.scope_id_redacted", "scope id must be safe and redacted")
    if not isinstance(scope.get("visibility"), str) or scope.get("visibility") not in SESSION_VISIBILITY:
        return _fail("schema_bad_session_scope", "envelope.session_scope.visibility", "visibility is not allowed")

    if scope.get("scope_type") in {"group", "group_context"}:
        if "redacted" not in str(scope.get("scope_id_redacted")):
            return _fail("schema_bad_session_scope", "envelope.session_scope.scope_id_redacted", "group scope id must be redacted")
        if scope.get("visibility") not in GROUP_VISIBILITY:
            return _fail("schema_bad_session_scope", "envelope.session_scope.visibility", "group scope visibility is not allowed")
    return None


def _validate_loop_guard(loop_guard: Mapping[str, Any], target_agent: Any) -> Optional[Dict[str, Any]]:
    required = ("max_hops", "hop_count", "seen_by", "idempotency_key", "cooldown_seconds", "reply_policy")
    missing = _require_nested_fields(loop_guard, required, "envelope.loop_guard", "schema_bad_loop_guard")
    if missing:
        return missing

    max_hops = loop_guard.get("max_hops")
    hop_count = loop_guard.get("hop_count")
    cooldown = loop_guard.get("cooldown_seconds")
    seen_by = loop_guard.get("seen_by")
    idempotency_key = loop_guard.get("idempotency_key")
    reply_policy = loop_guard.get("reply_policy")

    if not _is_int(max_hops) or not 1 <= int(max_hops) <= 16:
        return _fail("schema_bad_loop_guard", "envelope.loop_guard.max_hops", "max_hops must be an integer in range 1..16")
    if not _is_int(hop_count) or int(hop_count) < 0:
        return _fail("schema_bad_loop_guard", "envelope.loop_guard.hop_count", "hop_count must be a non-negative integer")
    if int(hop_count) >= int(max_hops) and loop_guard.get("schema_allows_terminal_hop_for_legacy_gate") is not True:
        return _fail("schema_bad_loop_guard", "envelope.loop_guard.hop_count", "hop_count must be less than max_hops unless explicitly delegated to legacy gate")
    if not isinstance(seen_by, list) or not all(isinstance(item, str) and _safe_agent_id(item) for item in seen_by):
        return _fail("schema_bad_loop_guard", "envelope.loop_guard.seen_by", "seen_by must contain only safe agent ids")
    if isinstance(target_agent, str) and target_agent in seen_by:
        return _fail("schema_bad_loop_guard", "envelope.loop_guard.seen_by", "target agent already appears in seen_by")
    if not isinstance(idempotency_key, str) or not _safe_id(idempotency_key) or not idempotency_key.startswith(("idem_", "idem:")):
        return _fail("schema_bad_loop_guard", "envelope.loop_guard.idempotency_key", "idempotency_key must be safe and idempotency-prefixed")
    if not _is_int(cooldown) or not 0 <= int(cooldown) <= 3600:
        return _fail("schema_bad_loop_guard", "envelope.loop_guard.cooldown_seconds", "cooldown_seconds must be an integer in range 0..3600")
    if not isinstance(reply_policy, str) or reply_policy not in REPLY_POLICIES:
        return _fail("schema_bad_loop_guard", "envelope.loop_guard.reply_policy", "reply_policy is not allowed")
    return None


def validate_message_envelope(message: dict, now: Optional[datetime | str] = None) -> dict:
    """Validate one Agent Bus A1.1 redacted message envelope.

    Args:
        message: Candidate message object.  It must contain an ``envelope``
            object.  The top-level ``type`` field is only a compatibility echo;
            ``envelope.message_type`` is canonical.
        now: Optional timezone-aware ``datetime`` or ISO datetime string used for
            TTL expiration checks.  If omitted, the current UTC clock is used.

    Returns:
        A sanitized dict with ``valid``, ``failure_class``, ``reason``,
        ``errors`` and, on success, ``normalized``.
    """
    if not isinstance(message, dict):
        return _fail("schema_type_error", "message", "message must be a JSON object")

    envelope = message.get("envelope")
    if not isinstance(envelope, dict):
        return _fail("schema_type_error", "envelope", "envelope must be a JSON object")

    for field in REQUIRED_ENVELOPE_FIELDS:
        if field not in envelope:
            return _fail("schema_missing_required", f"envelope.{field}", "required envelope field is missing")

    working_envelope = dict(envelope)
    working_message = dict(message)
    working_message["envelope"] = working_envelope
    message = working_message
    envelope = working_envelope

    string_fields = (
        "message_id",
        "message_type",
        "correlation_id",
        "trace_id",
        "source_agent",
        "target_agent",
        "risk_level",
        "capability_requested",
        "created_at",
    )
    for field in string_fields:
        if not isinstance(envelope.get(field), str):
            return _fail("schema_type_error", f"envelope.{field}", "field must be a string")
    if envelope.get("parent_message_id") is not None and not isinstance(envelope.get("parent_message_id"), str):
        return _fail("schema_type_error", "envelope.parent_message_id", "parent_message_id must be string or null")
    if envelope.get("payload_ref") is not None and not isinstance(envelope.get("payload_ref"), str):
        return _fail("schema_type_error", "envelope.payload_ref", "payload_ref must be string or null")
    if envelope.get("payload_digest") is not None and not isinstance(envelope.get("payload_digest"), str):
        return _fail("schema_type_error", "envelope.payload_digest", "payload_digest must be string or null")
    if not _is_int(envelope.get("ttl_seconds")):
        return _fail("schema_type_error", "envelope.ttl_seconds", "ttl_seconds must be an integer")
    if not _is_bool(envelope.get("requires_owner_approval")):
        return _fail("schema_type_error", "envelope.requires_owner_approval", "requires_owner_approval must be boolean")
    if not _is_bool(envelope.get("requires_second_factor")):
        return _fail("schema_type_error", "envelope.requires_second_factor", "requires_second_factor must be boolean")
    if not isinstance(envelope.get("actor_context"), dict):
        return _fail("schema_type_error", "envelope.actor_context", "actor_context must be an object")
    if not isinstance(envelope.get("session_scope"), dict):
        return _fail("schema_type_error", "envelope.session_scope", "session_scope must be an object")
    if not isinstance(envelope.get("loop_guard"), dict):
        return _fail("schema_type_error", "envelope.loop_guard", "loop_guard must be an object")

    if envelope["message_type"] not in MESSAGE_TYPES:
        return _fail("schema_enum_error", "envelope.message_type", "message_type is not allowed")
    if "type" in message and message.get("type") != envelope["message_type"]:
        return _fail("schema_format_error", "type", "top-level type must match envelope.message_type")
    if envelope["risk_level"] not in RISK_LEVELS:
        return _fail("schema_enum_error", "envelope.risk_level", "risk_level is not allowed")
    if envelope["capability_requested"] not in CAPABILITIES:
        return _fail("schema_enum_error", "envelope.capability_requested", "capability_requested is not allowed")

    id_fields = (
        "message_id",
        "correlation_id",
        "trace_id",
        "source_agent",
        "target_agent",
    )
    for field in id_fields:
        if not _safe_id(envelope.get(field)):
            return _fail("schema_format_error", f"envelope.{field}", "identifier must be safe slug-like or UUID")
    if envelope.get("parent_message_id") is not None and not _safe_id(envelope.get("parent_message_id")):
        return _fail("schema_format_error", "envelope.parent_message_id", "parent_message_id must be safe slug-like or UUID")

    created_at = _parse_iso_datetime(envelope["created_at"])
    if created_at is None:
        return _fail("schema_format_error", "envelope.created_at", "created_at must be an ISO datetime with timezone")

    ttl_seconds = envelope["ttl_seconds"]
    if not 1 <= int(ttl_seconds) <= 3600:
        return _fail("schema_bad_ttl", "envelope.ttl_seconds", "ttl_seconds must be in range 1..3600")

    now_dt, now_error = _coerce_now(now)
    if now_error or now_dt is None:
        return _fail("schema_format_error", "now", now_error or "now is invalid")

    sensitive = _scan_sensitive(message)
    if sensitive:
        field_path, reason = sensitive
        if field_path == "message.envelope.payload_ref":
            return _fail("schema_forbidden_payload_ref", "envelope.payload_ref", "payload_ref contains forbidden material")
        return _fail("schema_sensitive_material", field_path, reason)

    actor_result = _validate_actor_context(envelope["actor_context"], envelope)
    if actor_result:
        return actor_result

    scope_result = _validate_session_scope(envelope["session_scope"])
    if scope_result:
        return scope_result

    loop_result = _validate_loop_guard(envelope["loop_guard"], envelope.get("target_agent"))
    if loop_result:
        return loop_result

    payload_ref = envelope.get("payload_ref")
    payload_digest = envelope.get("payload_digest")
    if payload_ref is None:
        if payload_digest is not None:
            return _fail("schema_bad_digest", "envelope.payload_digest", "null payload_ref requires null payload_digest")
        if envelope["message_type"] not in NO_PAYLOAD_MESSAGE_TYPES:
            return _fail("schema_forbidden_payload_ref", "envelope.payload_ref", "message_type requires a redacted payload reference")
    else:
        if _payload_ref_forbidden(payload_ref):
            return _fail("schema_forbidden_payload_ref", "envelope.payload_ref", "payload_ref uses a forbidden scheme or path")
        if not isinstance(payload_digest, str) or not DIGEST_RE.fullmatch(payload_digest):
            return _fail("schema_bad_digest", "envelope.payload_digest", "payload_digest must be sha256 lowercase hex")

    if "payload_inline_redacted" in message:
        inline_payload = message.get("payload_inline_redacted")
        if not _is_json_value(inline_payload):
            return _fail("schema_type_error", "payload_inline_redacted", "payload_inline_redacted must be a JSON value")
        if payload_ref is None:
            return _fail("schema_bad_digest", "payload_inline_redacted", "inline payload requires non-null payload_ref and digest")
        expected_digest = sha256_payload(inline_payload)
        if payload_digest != expected_digest:
            return _fail("schema_digest_mismatch", "envelope.payload_digest", "payload_digest does not match inline redacted payload")

    normalized = copy.deepcopy(message)
    normalized.setdefault("type", envelope["message_type"])
    normalized["envelope"]["message_type"] = envelope["message_type"]
    actor_norm = normalized["envelope"].get("actor_context")
    if isinstance(actor_norm, dict):
        if "actor_id_redacted" not in actor_norm and "actor_id" in actor_norm:
            actor_norm["actor_id_redacted"] = actor_norm.get("actor_id")
        if "channel" not in actor_norm and "source_channel" in actor_norm:
            actor_norm["channel"] = actor_norm.get("source_channel")
        if "source_trust" not in actor_norm and "trust_level" in actor_norm:
            actor_norm["source_trust"] = actor_norm.get("trust_level")
    scope_norm = normalized["envelope"].get("session_scope")
    if isinstance(scope_norm, dict):
        if "scope_id_redacted" not in scope_norm and "scope_id" in scope_norm:
            scope_norm["scope_id_redacted"] = scope_norm.get("scope_id")
        if "visibility" not in scope_norm:
            scope_norm["visibility"] = "group_redacted" if scope_norm.get("scope_type") in {"group", "group_context"} else "internal_only"
    return _result(valid=True, normalized=normalized)


__all__ = [
    "RELEASE_DECISION",
    "SCHEMA_VERSION",
    "sha256_payload",
    "stable_json",
    "validate_message_envelope",
]
