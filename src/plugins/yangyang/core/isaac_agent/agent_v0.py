#!/usr/bin/env python3
"""Isaac I叔 Agent v0.1 — prompt + LLM + readonly tool selection.

v0.1 范围（2026-06-10，前辈拍板）：
- 接 V4 Pro（DeepSeek 官方），通过 model_router 走 target=isaac 路由
- I叔 prompt 走 prompt_v0.md（I5.1 草稿改写）
- 5 个只读工具的 schema 挂给 LLM（health/workspace/audit/status/dry_run_plan）
- I叔 LLM 负责"选哪个工具 + 解释"；v0.2 仅允许 agentbus_factory 走真实只读执行闭环
- 记忆系统：JSONL 落盘，只记 prompt 版本 / 工具清单 / 决策日志
- 第二令牌搁置
- 群聊/非 owner 锁死（I叔 agent 只服务 Agent Bus，不直接接收 QQ 消息）
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---- 路径常量 ----
ISAAC_AGENT_DIR = Path(__file__).resolve().parent
PROMPT_PATH = ISAAC_AGENT_DIR / "prompt_v0.md"
MEMORY_PATH = ISAAC_AGENT_DIR / "memory.jsonl"
TARGET_AGENT = "isaac"
ISAAC_MODEL_TIER = "v4_pro"  # 默认回退；生产可用 runtime_cfg: isaac.model_profile 覆盖

READONLY_TOOLS = [
    {
        "name": "health",
        "description": "读取系统 health 快照：service 状态、OneBot 连接、最近错误。不修改任何东西。",
        "risk": "low",
    },
    {
        "name": "workspace",
        "description": "读取项目概览：关键目录、audit 行数、最近文件。不修改任何东西。",
        "risk": "low",
    },
    {
        "name": "audit",
        "description": "读取 P0 audit 日志：handled/denied/ignored 分布、来源、任务类型。不修改任何东西。",
        "risk": "low",
    },
    {
        "name": "status",
        "description": "列出 P0 能力矩阵：health/workspace/audit/help 的可用性。不修改任何东西。",
        "risk": "low",
    },
    {
        "name": "dry_run_plan",
        "description": "把一个提议动作分类成 10 类（audit/status/health/workspace/.../deploy）并打高危标记。不修改任何东西。",
        "risk": "low",
    },
    {
        "name": "agentbus_factory",
        "description": "读取 AgentBus/Nekro worker 工厂最近一次 run、collector 产物、validator 验尸结果。不派工、不修改任何东西。",
        "risk": "low",
    },
]

FORBIDDEN_TOOL_PATTERNS = (
    "write", "edit", "delete", "rm", "mv", "cp",
    "deploy", "restart", "systemctl", "service",
    "shell", "ssh", "scp", "bash", "sh", "subprocess",
    "config_write", "write_config", "memory_write", "memory_delete",
)

# v0.2 小刀：只让 AgentBus 工厂报告走真实只读执行闭环。
# 其余 readonly tools 继续只做 LLM 选择 + P0 builtin worker 派发，避免一次性扩大执行面。
V02_EXECUTABLE_TOOLS = frozenset({"agentbus_factory"})

_FORBIDDEN_OUTPUT_FRAGMENTS = (
    "/root/data",
    "/mnt",
    "/opt/yangyang_nonebot",
    ".env",
    "runtime_config",
    "long_term/memories.jsonl",
    "base_url",
    "api_key",
    "token",
    "secret",
    "password",
    "335059272",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class IsaacDecision:
    ts: str
    request_id: str
    user_intent: str
    chosen_tool: str
    tool_existed: bool
    reason: str
    blocked_reason: str = ""
    model_tier: str = ISAAC_MODEL_TIER
    prompt_sha: str = ""
    tool_registry_sha: str = ""
    raw_llm_output: str = ""
    tool_executed: bool = False
    tool_output: Dict[str, Any] = field(default_factory=dict)
    tool_latency_ms: int = 0
    tool_blocked_reason: str = ""


class IsaacMemory:
    """I叔 记忆系统 v0.1 — JSONL 落盘，只记三类事。"""

    def __init__(self, path: Path = MEMORY_PATH):
        self.path = path
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def append(self, decision: IsaacDecision) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(decision), ensure_ascii=False) + "\n")

    def tail(self, n: int = 10) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        out: List[Dict[str, Any]] = []
        for line in lines[-n:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def count(self) -> int:
        if not self.path.exists():
            return 0
        return sum(1 for _ in self.path.open("r", encoding="utf-8") if _.strip())


class IsaacLLM:
    """I叔 LLM 客户端 v0.3 — 通过 model_router 走独立 profile，不重复实现 provider。"""

    def __init__(self, model_router: Any, model_tier: str = ISAAC_MODEL_TIER):
        self.router = model_router
        self.model_tier = str(model_tier or ISAAC_MODEL_TIER)

    def think(
        self,
        system_prompt: str,
        user_intent: str,
        tool_registry: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """调 model_router 让 V4 Pro 选工具 + 解释。

        返回 dict: {chosen_tool, reason, raw_text, error}
        不抛异常，错误走 error 字段。
        """
        tool_lines = "\n".join(
            f"- {t['name']}: {t['description']} (risk={t['risk']})"
            for t in tool_registry
        )
        user_prompt = (
            f"Available readonly tools:\n{tool_lines}\n\n"
            f"User intent: {user_intent}\n\n"
            "Respond in JSON only: "
            '{"chosen_tool": "<tool_name_or_null>", "reason": "<one short sentence>"}\n'
            "If no readonly tool fits, set chosen_tool=null and explain why."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            # model_router.call_via_tier 走指定 tier，不动私聊/群聊 active
            response = self.router.call_via_tier(
                tier=self.model_tier,
                messages=messages,
                target_agent=TARGET_AGENT,
            )
            used_tier = self.model_tier
            if isinstance(response, dict):
                text = str(response.get("content") or response.get("text") or "").strip()
                used_tier = str(response.get("tier") or response.get("actual_tier") or self.model_tier)
            elif isinstance(response, (tuple, list)) and response:
                text = str(response[0] or "").strip()
                if len(response) > 1 and response[1]:
                    used_tier = str(response[1])
            else:
                text = str(response or "").strip()
            parsed = self._parse_json_choice(text)
            return {
                "chosen_tool": parsed.get("chosen_tool"),
                "reason": parsed.get("reason", ""),
                "raw_text": text,
                "used_tier": used_tier,
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "chosen_tool": None,
                "reason": "",
                "raw_text": "",
                "error": f"{type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _parse_json_choice(text: str) -> Dict[str, Any]:
        """从 LLM 输出里抽 JSON，允许 ```json ... ``` 包裹。"""
        if not text:
            return {"chosen_tool": None, "reason": ""}
        s = text.strip()
        # 去 markdown 包裹
        if s.startswith("```"):
            s = s.strip("`")
            if s.startswith("json"):
                s = s[4:]
            s = s.strip()
        # 找第一个 { 到最后一个 }
        start = s.find("{")
        end = s.rfind("}")
        if start < 0 or end < 0 or end <= start:
            return {"chosen_tool": None, "reason": s[:200]}
        try:
            return json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            return {"chosen_tool": None, "reason": s[start:end + 1][:200]}


def _redact_tool_output(value: Any) -> Any:
    """Redact host-sensitive strings from readonly tool output before memory/audit."""
    if isinstance(value, dict):
        return {str(k): _redact_tool_output(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_tool_output(v) for v in value]
    if isinstance(value, tuple):
        return [_redact_tool_output(v) for v in value]
    if isinstance(value, str):
        out = value
        lowered = out.lower()
        for frag in _FORBIDDEN_OUTPUT_FRAGMENTS:
            if frag.lower() in lowered:
                out = out.replace(frag, "[redacted]")
                lowered = out.lower()
        # A second pass for common absolute path prefixes not matched exactly.
        if out.startswith(("/root/", "/mnt/", "/opt/")):
            return "[redacted_path]"
        return out[:4000]
    return value


def _compact_tool_output(value: Any, *, limit: int = 4000) -> Dict[str, Any]:
    """Return a JSON-safe, bounded dict for decision memory/audit."""
    redacted = _redact_tool_output(value)
    try:
        blob = json.dumps(redacted, ensure_ascii=False, sort_keys=True)
    except TypeError:
        redacted = {"status": "non_json_output", "repr": repr(redacted)[:limit]}
        blob = json.dumps(redacted, ensure_ascii=False, sort_keys=True)
    if len(blob) <= limit:
        if isinstance(redacted, dict):
            return redacted
        return {"status": "ok", "value": redacted}
    return {
        "status": "truncated",
        "truncated": True,
        "chars": len(blob),
        "preview": blob[:limit],
    }


def _runtime_cfg_get(runtime_cfg: Any, path: str, default: Any = None) -> Any:
    try:
        if runtime_cfg is not None and hasattr(runtime_cfg, "get"):
            value = runtime_cfg.get(path, default)
            return default if value is None else value
    except Exception:
        return default
    return default


def _resolve_isaac_model_tier(model_router: Any) -> str:
    runtime_cfg = getattr(model_router, "runtime_cfg", None)
    value = _runtime_cfg_get(runtime_cfg, "isaac.model_profile", "")
    if not value:
        value = _runtime_cfg_get(runtime_cfg, "isaac.model_tier", "")
    return str(value or ISAAC_MODEL_TIER)


class IsaacAgent:
    """I叔 Agent v0.2 — prompt + LLM + 记忆 + 最小 readonly 执行闭环。"""

    def __init__(self, model_router: Any, prompt_path: Path = PROMPT_PATH, memory_path: Path = MEMORY_PATH, model_tier: str | None = None):
        self.prompt_path = prompt_path
        self.prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
        self.prompt_sha = _sha256_file(prompt_path)
        self.tool_registry = list(READONLY_TOOLS)
        self.tool_registry_sha = _sha256_text(json.dumps(self.tool_registry, sort_keys=True, ensure_ascii=False))
        self.model_tier = str(model_tier or _resolve_isaac_model_tier(model_router))
        self.llm = IsaacLLM(model_router, model_tier=self.model_tier)
        self.memory = IsaacMemory(memory_path)

    def _is_forbidden(self, tool_name: str) -> bool:
        if not tool_name:
            return False
        t = tool_name.lower()
        return any(p in t for p in FORBIDDEN_TOOL_PATTERNS)

    def _is_in_registry(self, tool_name: str) -> bool:
        if not tool_name:
            return False
        return any(t["name"] == tool_name for t in self.tool_registry)

    def _is_executable_in_v02(self, tool_name: str) -> bool:
        return bool(tool_name and tool_name in V02_EXECUTABLE_TOOLS)

    def _execute_readonly_tool(self, tool_name: str) -> tuple[bool, Dict[str, Any], int, str]:
        """Execute the tiny v0.2 readonly whitelist.  Never raises."""
        if not tool_name:
            return False, {}, 0, "no_tool_chosen"
        if self._is_forbidden(tool_name):
            return False, {"status": "blocked", "tool": tool_name}, 0, f"forbidden_tool_requested: {tool_name}"
        if not self._is_in_registry(tool_name):
            return False, {"status": "blocked", "tool": tool_name}, 0, f"tool_not_in_registry: {tool_name}"
        if not self._is_executable_in_v02(tool_name):
            return False, {"status": "not_executable_in_v02", "tool": tool_name}, 0, "not_executable_in_v02"

        start = time.monotonic()
        try:
            if tool_name == "agentbus_factory":
                try:
                    from ..isaac_agentbus_factory_report import build_agentbus_factory_report
                except Exception:
                    # Direct-file test loading fallback.
                    import importlib.util
                    import sys

                    report_path = ISAAC_AGENT_DIR.parent / "isaac_agentbus_factory_report.py"
                    spec = importlib.util.spec_from_file_location("isaac_agentbus_factory_report_for_agent_v02", report_path)
                    if spec is None or spec.loader is None:
                        raise ImportError(f"cannot load {report_path}")
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[spec.name] = mod
                    spec.loader.exec_module(mod)
                    build_agentbus_factory_report = mod.build_agentbus_factory_report  # type: ignore[attr-defined]
                raw_output = build_agentbus_factory_report()
            else:  # pragma: no cover - V02_EXECUTABLE_TOOLS locks this out.
                return False, {"status": "unknown_tool", "tool": tool_name}, 0, f"unknown_tool: {tool_name}"
            latency = int((time.monotonic() - start) * 1000)
            return True, _compact_tool_output(raw_output), latency, ""
        except Exception as exc:  # noqa: BLE001 - fail-soft by design.
            latency = int((time.monotonic() - start) * 1000)
            return True, {"status": "tool_exception", "tool": tool_name}, latency, f"{type(exc).__name__}: {exc}"

    def think(self, user_intent: str, request_id: str = "") -> IsaacDecision:
        """I叔 思考一次：调 LLM 选工具，校验，写 decision log。"""
        llm_out = self.llm.think(
            system_prompt=self.prompt_text,
            user_intent=user_intent,
            tool_registry=self.tool_registry,
        )

        chosen = llm_out.get("chosen_tool")
        reason = llm_out.get("reason", "")
        raw = llm_out.get("raw_text", "")
        err = llm_out.get("error", "")

        blocked_reason = ""
        if err:
            blocked_reason = f"llm_error: {err}"
            chosen = None
        elif self._is_forbidden(chosen or ""):
            blocked_reason = f"forbidden_tool_requested: {chosen}"
            chosen = None
        elif chosen and not self._is_in_registry(chosen):
            blocked_reason = f"tool_not_in_registry: {chosen}"
            chosen = None

        decision = IsaacDecision(
            ts=_utc_now(),
            request_id=request_id or hashlib.md5(
                f"{_utc_now()}-{user_intent}".encode()
            ).hexdigest()[:12],
            user_intent=user_intent[:500],
            chosen_tool=chosen or "",
            tool_existed=bool(chosen and self._is_in_registry(chosen)),
            reason=reason[:300],
            blocked_reason=blocked_reason,
            model_tier=str(llm_out.get("used_tier") or self.model_tier),
            prompt_sha=self.prompt_sha,
            tool_registry_sha=self.tool_registry_sha,
            raw_llm_output=raw[:500],
        )
        if decision.chosen_tool:
            executed, output, latency_ms, tool_reason = self._execute_readonly_tool(decision.chosen_tool)
            decision.tool_executed = executed
            decision.tool_output = output
            decision.tool_latency_ms = latency_ms
            decision.tool_blocked_reason = tool_reason
        self.memory.append(decision)
        return decision

    def stats(self) -> Dict[str, Any]:
        decisions = self.memory.tail(100)
        return {
            "prompt_sha": self.prompt_sha,
            "tool_registry_sha": self.tool_registry_sha,
            "tool_count": len(self.tool_registry),
            "memory_count": self.memory.count(),
            "recent_decisions": decisions[-5:],
        }
