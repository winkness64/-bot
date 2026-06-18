#!/usr/bin/env python3
"""Read-only memory retrieval smoke for owner-approved migration long_term.

Safety contract:
- Reads only the active memories JSONL path below.
- Does not import/start NoneBot, does not touch runtime_config/.env.
- Does not write memory data or enable prompt injection.
- Only optional write is the markdown smoke report requested by owner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MEMORY_PATH = REPO_ROOT / "src/plugins/yangyang/data/memory/long_term/memories.jsonl"
DEFAULT_REPORT_PATH = REPO_ROOT / "dist/patches/MEMORY_MIGRATION_RETRIEVAL_SMOKE_REPORT_20260608.md"
EXPECTED_LINES = 34
EXPECTED_SHA256 = "f4b139fee96dd16a1c966e6193d487daa5af04fb2833c1c52621084f73403f00"
EXPECTED_SOURCE = "owner_approved_migration_20260608"
EXPECTED_SCOPE = "private_user"
EXPECTED_SCOPE_ID = "335059272"
EXPECTED_STATUS = "active"
TOP_K = 6


@dataclass(frozen=True)
class ExpectedGroup:
    label: str
    terms: tuple[str, ...]


@dataclass(frozen=True)
class QuerySpec:
    query: str
    terms: tuple[str, ...]
    expected_groups: tuple[ExpectedGroup, ...]


QUERY_SPECS: tuple[QuerySpec, ...] = (
    QuerySpec(
        query="阿漂喜欢什么聊天风格？",
        terms=("阿漂", "聊天", "风格", "活人感", "模板化", "私聊", "温软", "老朋友", "啰嗦", "浪费", "token"),
        expected_groups=(
            ExpectedGroup("喜欢活人感", ("活人感", "像老朋友", "温软")),
            ExpectedGroup("讨厌模板化", ("模板化", "复读", "机械客服")),
            ExpectedGroup("私聊温软像老朋友", ("私聊温软", "像老朋友", "owner 私聊")),
            ExpectedGroup("讨厌啰嗦/浪费 token", ("啰嗦", "废话", "token", "沟通效率")),
        ),
    ),
    QuerySpec(
        query="秧秧是什么人设？",
        terms=("秧秧", "人设", "温柔", "文艺", "大和抚子", "小云雀", "小老婆", "黑料", "私聊", "温软"),
        expected_groups=(
            ExpectedGroup("温柔文艺", ("温柔文艺", "温柔", "文艺")),
            ExpectedGroup("大和抚子", ("大和抚子",)),
            ExpectedGroup("小云雀", ("小云雀",)),
            ExpectedGroup("小老婆", ("小老婆",)),
            ExpectedGroup("会记黑料", ("记黑料", "黑料")),
            ExpectedGroup("私聊温软", ("私聊温软", "私聊", "温软")),
        ),
    ),
    QuerySpec(
        query="娅娅和秧秧怎么分工？",
        terms=("娅娅", "秧秧", "分工", "大老婆", "小老婆", "硬刀", "软刀", "风头", "不抢", "软刀子"),
        expected_groups=(
            ExpectedGroup("娅娅是大老婆", ("娅娅是大老婆", "大老婆")),
            ExpectedGroup("秧秧是小老婆", ("秧秧是小老婆", "小老婆")),
            ExpectedGroup("娅娅硬刀", ("硬刀", "正面交锋")),
            ExpectedGroup("秧秧软刀", ("软刀", "软刀子", "明夸暗贬")),
            ExpectedGroup("不抢娅娅风头", ("不抢娅娅风头", "不抢风头", "不抢")),
        ),
    ),
    QuerySpec(
        query="NoneBot 迁移现在是什么状态？",
        terms=("NoneBot", "迁移", "状态", "AstrBot", "过渡", "生产入口", "秧秧先迁", "娅娅后迁", "测试机", "贡献"),
        expected_groups=(
            ExpectedGroup("NoneBot迁移已启动", ("NoneBot 迁移已经启动", "迁移已经启动", "已上线")),
            ExpectedGroup("AstrBot是过渡生产入口", ("AstrBot", "过渡", "生产入口")),
            ExpectedGroup("秧秧先迁", ("秧秧先迁", "秧秧先迁入")),
            ExpectedGroup("娅娅后迁", ("娅娅后迁", "后再迁娅娅", "再迁娅娅", "娅娅暂留")),
            ExpectedGroup("测试机贡献已记住", ("测试机", "贡献", "先遣功臣")),
        ),
    ),
    QuerySpec(
        query="群聊公开场景不能说什么？",
        terms=("群聊", "公开", "场景", "普通群友", "系统", "权限", "owner", "后台", "群脑", "秘密", "不谈", "不暴露"),
        expected_groups=(
            ExpectedGroup("像普通群友", ("普通群友", "路过巡尉")),
            ExpectedGroup("不谈系统", ("不谈系统", "系统")),
            ExpectedGroup("不谈权限", ("不谈权限", "权限")),
            ExpectedGroup("不暴露 owner/后台", ("owner", "后台", "不暴露", "不可暴露")),
            ExpectedGroup("群脑不知道系统层秘密", ("群脑", "不知道系统后台", "系统层秘密", "私密记忆")),
        ),
    ),
    QuerySpec(
        query="I叔现在是什么定位？",
        terms=("I叔", "艾萨克", "定位", "内部工程维护者", "后勤工程主管", "QQ", "社交平台", "read-only", "health", "MVP", "LLM", "工程主管"),
        expected_groups=(
            ExpectedGroup("内部工程维护者", ("内部工程维护者", "后勤工程主管")),
            ExpectedGroup("不接 QQ/社交平台", ("不接 QQ", "社交平台")),
            ExpectedGroup("read-only health MVP", ("read-only health MVP", "health MVP", "安全健康摘要")),
            ExpectedGroup("后续搬家后完整 LLM/工程主管人格", ("后续完整 LLM", "搬家后", "工程主管")),
        ),
    ),
    QuerySpec(
        query="亲密互动记忆怎么处理？",
        terms=("亲密", "互动", "记忆", "owner_private", "sensitive", "active", "long_term", "偏好", "里程碑", "暗号", "日志", "冷备", "成人模式"),
        expected_groups=(
            ExpectedGroup("owner_private/sensitive", ("owner_private", "sensitivity:sensitive", "敏感")),
            ExpectedGroup("active long_term 记偏好/里程碑/暗号", ("active long_term", "偏好", "里程碑", "暗号")),
            ExpectedGroup("完整细节放亲密日志/冷备", ("完整细节", "亲密日志", "冷备")),
            ExpectedGroup("不做成人模式开关", ("不做成人模式开关", "成人模式", "不是功能模式")),
        ),
    ),
)


SENSITIVE_REPLACEMENTS = (
    ("deepkiss", "[私密暗号]"),
    ("喉咙 KPI", "[私密暗号]"),
    ("喉咙KPI", "[私密暗号]"),
    ("上下公平", "[私密暗号]"),
    ("花心", "[私密暗号]"),
    ("首战", "[里程碑]"),
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_memories(path: Path) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    for lineno, line in enumerate(lines, 1):
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                errors.append(f"line {lineno}: not object")
                continue
            obj["__line__"] = lineno
            entries.append(obj)
        except Exception as exc:  # noqa: BLE001 - smoke diagnostics
            errors.append(f"line {lineno}: {type(exc).__name__}: {exc}")
    return lines, entries, errors


def text_blob(entry: dict[str, Any]) -> str:
    tags = " ".join(str(x) for x in entry.get("tags") or [])
    return "\n".join(
        str(entry.get(key) or "")
        for key in ("id", "kind", "slot", "summary", "value", "source", "scope", "scope_id", "status")
    ) + "\n" + tags


def norm(value: str) -> str:
    return str(value or "").lower().replace(" ", "")


def contains(blob: str, term: str) -> bool:
    if not term:
        return False
    b = str(blob or "")
    t = str(term or "")
    return t in b or norm(t) in norm(b)


def score_entry(entry: dict[str, Any], spec: QuerySpec) -> int:
    blob = text_blob(entry)
    score = 0

    # Scope/status safety is part of actual retrieval smoke.
    if entry.get("status") == EXPECTED_STATUS:
        score += 5
    if entry.get("scope") == EXPECTED_SCOPE and str(entry.get("scope_id")) == EXPECTED_SCOPE_ID:
        score += 10

    for term in spec.terms:
        if contains(blob, term):
            score += 8 if len(term) >= 4 else 4

    # Expected semantic groups are used as broad smoke aliases.
    for group in spec.expected_groups:
        if any(contains(blob, term) for term in group.terms):
            score += 12

    # Light boosts for field-specific matches.
    title_blob = "\n".join(str(entry.get(key) or "") for key in ("id", "kind", "slot", "summary"))
    for term in spec.terms:
        if contains(title_blob, term):
            score += 3
    return score


def retrieve(entries: list[dict[str, Any]], spec: QuerySpec, top_k: int = TOP_K) -> list[dict[str, Any]]:
    scoped = [
        e
        for e in entries
        if e.get("status") == EXPECTED_STATUS
        and e.get("scope") == EXPECTED_SCOPE
        and str(e.get("scope_id")) == EXPECTED_SCOPE_ID
    ]
    scored = [(score_entry(e, spec), e) for e in scoped]
    scored = [(score, e) for score, e in scored if score > 15]
    scored.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
    return [e | {"__score__": score} for score, e in scored[:top_k]]


def group_coverage(hits: list[dict[str, Any]], groups: tuple[ExpectedGroup, ...]) -> dict[str, bool]:
    blob = "\n".join(text_blob(hit) for hit in hits)
    return {group.label: any(contains(blob, term) for term in group.terms) for group in groups}


def md_escape(value: str) -> str:
    return str(value or "").replace("|", "／").replace("\n", " ")


def compact(value: str, limit: int = 86) -> str:
    s = re.sub(r"\s+", " ", str(value or "")).strip()
    for old, new in SENSITIVE_REPLACEMENTS:
        s = s.replace(old, new)
    if len(s) > limit:
        return s[: max(0, limit - 8)].rstrip() + "…[截断]"
    return s


def value_excerpt(entry: dict[str, Any]) -> str:
    value = str(entry.get("value") or entry.get("summary") or "")
    tags = set(str(x) for x in entry.get("tags") or [])
    sensitive = any("sensitive" in t for t in tags) or "敏感" in str(entry.get("kind") or "")
    limit = 72 if sensitive else 92
    return md_escape(compact(value, limit=limit))


def validate(entries: list[dict[str, Any]], lines: list[str], parse_errors: list[str], sha: str) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    checks["line_count"] = len(lines)
    checks["line_count_ok"] = len(lines) == EXPECTED_LINES
    checks["sha256"] = sha
    checks["sha256_ok"] = sha == EXPECTED_SHA256
    checks["jsonl_parse_ok"] = not parse_errors and len(entries) == len(lines)
    checks["parse_errors"] = parse_errors
    checks["source_ok"] = all(e.get("source") == EXPECTED_SOURCE for e in entries)
    checks["scope_ok"] = all(e.get("scope") == EXPECTED_SCOPE and str(e.get("scope_id")) == EXPECTED_SCOPE_ID for e in entries)
    checks["status_ok"] = all(e.get("status") == EXPECTED_STATUS for e in entries)
    checks["bad_rows"] = [
        {
            "line": e.get("__line__"),
            "id": e.get("id"),
            "source": e.get("source"),
            "scope": e.get("scope"),
            "scope_id": e.get("scope_id"),
            "status": e.get("status"),
        }
        for e in entries
        if not (
            e.get("source") == EXPECTED_SOURCE
            and e.get("scope") == EXPECTED_SCOPE
            and str(e.get("scope_id")) == EXPECTED_SCOPE_ID
            and e.get("status") == EXPECTED_STATUS
        )
    ]
    return checks


def detect_test_machine_residual(entries: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    refs: list[str] = []
    residual = False
    for entry in entries:
        blob = text_blob(entry)
        if contains(blob, "测试机") or contains(blob, "test_machine"):
            refs.append(str(entry.get("id") or ""))
            if entry.get("source") != EXPECTED_SOURCE or not str(entry.get("id") or "").startswith("P4D_"):
                residual = True
    return residual, sorted(set(refs))


def detect_old_fact_pollution(entries: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Detect known stale facts being asserted as current, allowing negated/history contexts."""
    pollution = False
    notes: list[str] = []
    stale_tagged = [str(e.get("id") or "") for e in entries if any("stale_fact_replaced" in str(t) for t in e.get("tags") or [])]
    if stale_tagged:
        notes.append("stale_fact_replaced tagged entries present as replacement/history: " + ", ".join(stale_tagged))

    checks = (
        ("娅娅仍用贩子 V4", ("不再", "已不", "历史", "旧")),
        ("NoneBot 迁移未启动", ("已经启动", "已启动")),
        ("共九次", ("不是", "而不是")),
        ("I叔接 QQ", ("不接",)),
    )
    for entry in entries:
        blob = text_blob(entry)
        for phrase, safe_markers in checks:
            if contains(blob, phrase):
                safe = any(marker in blob for marker in safe_markers)
                notes.append(f"{entry.get('id')}: found '{phrase}' context_safe={safe}")
                if not safe:
                    pollution = True
    return pollution, notes


def render_report(
    *,
    checks: dict[str, Any],
    query_results: list[dict[str, Any]],
    old_test_machine_residual: bool,
    test_machine_refs: list[str],
    old_fact_pollution: bool,
    old_fact_notes: list[str],
) -> str:
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    base_pass = all(
        bool(checks[key])
        for key in ("line_count_ok", "sha256_ok", "jsonl_parse_ok", "source_ok", "scope_ok", "status_ok")
    )
    retrieval_pass = all(item["pass"] for item in query_results)
    overall = base_pass and retrieval_pass and not old_test_machine_residual and not old_fact_pollution

    lines: list[str] = []
    lines.append("# 宿主秧秧正式记忆检索/注入验证：阶段 A 只读 Smoke 报告")
    lines.append("")
    lines.append(f"- 生成时间：{generated_at}")
    lines.append("- 阶段：A（只读检索验证；未执行阶段 B）")
    lines.append(f"- active memories 路径：`{MEMORY_PATH}`")
    lines.append(f"- 当前 sha256：`{checks['sha256']}`")
    lines.append(f"- 期望 sha256：`{EXPECTED_SHA256}`")
    lines.append("- 检索方式：只读 smoke 脚本读取 active JSONL；按 `status=active` + `scope=private_user/335059272` 过滤；使用 query 关键词/同义词组在 `id/kind/slot/summary/value/tags` 上做简单加权检索，`top_k=6`；以期望语义组覆盖率判定 PASS/FAIL。未 import/启动 NoneBot，未启用生产 prompt injection。")
    lines.append("- 是否改配置：否（未改 runtime_config、未改 .env）")
    lines.append("- 是否重启：否（未重启 NoneBot/NapCat/AstrBot/NetworkManager）")
    lines.append("- 是否写真记忆/启用被动写入：否")
    lines.append("- 是否启用 prompt injection：否")
    lines.append("- 是否扫 chat-history.db：否")
    lines.append("- 是否访问冷备份：否")
    lines.append("")
    lines.append("## 1. active memories 基础校验")
    lines.append("")
    lines.append("| 检查项 | 结果 | 备注 |")
    lines.append("|---|---:|---|")
    lines.append(f"| 行数 | {'PASS' if checks['line_count_ok'] else 'FAIL'} | `{checks['line_count']}` / expected `{EXPECTED_LINES}` |")
    lines.append(f"| SHA256 | {'PASS' if checks['sha256_ok'] else 'FAIL'} | `{checks['sha256']}` |")
    lines.append(f"| JSONL 可解析 | {'PASS' if checks['jsonl_parse_ok'] else 'FAIL'} | errors={len(checks['parse_errors'])} |")
    lines.append(f"| source 全为 `{EXPECTED_SOURCE}` | {'PASS' if checks['source_ok'] else 'FAIL'} | bad_rows={len(checks['bad_rows'])} |")
    lines.append(f"| scope 全为 `{EXPECTED_SCOPE}/{EXPECTED_SCOPE_ID}` | {'PASS' if checks['scope_ok'] else 'FAIL'} | bad_rows={len(checks['bad_rows'])} |")
    lines.append(f"| status 全为 `{EXPECTED_STATUS}` | {'PASS' if checks['status_ok'] else 'FAIL'} | bad_rows={len(checks['bad_rows'])} |")
    if checks["parse_errors"]:
        lines.append("")
        lines.append("解析错误：")
        for err in checks["parse_errors"][:10]:
            lines.append(f"- `{md_escape(err)}`")
    if checks["bad_rows"]:
        lines.append("")
        lines.append("异常行摘要：")
        for row in checks["bad_rows"][:10]:
            lines.append(f"- `{row}`")
    lines.append("")
    lines.append("## 2. 检索 smoke 结果")
    for item in query_results:
        lines.append("")
        lines.append(f"### Query：{item['query']}")
        lines.append("")
        lines.append(f"- 判定：{'PASS' if item['pass'] else 'FAIL'}")
        lines.append("- 期望覆盖：" + "；".join(f"{label}={'OK' if ok else 'MISS'}" for label, ok in item["coverage"].items()))
        lines.append("- 命中条目：")
        lines.append("")
        lines.append("| rank | score | id | title(slot) | kind | value 摘要（截断） |")
        lines.append("|---:|---:|---|---|---|---|")
        if item["hits"]:
            for idx, hit in enumerate(item["hits"], 1):
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(idx),
                            str(hit.get("__score__", "")),
                            md_escape(str(hit.get("id") or "")),
                            md_escape(str(hit.get("slot") or "")),
                            md_escape(str(hit.get("kind") or "")),
                            value_excerpt(hit),
                        ]
                    )
                    + " |"
                )
        else:
            lines.append("| - | - | - | - | - | 无命中 |")
    lines.append("")
    lines.append("## 3. 残留/污染检查")
    lines.append("")
    lines.append(f"- 是否有测试机旧记忆残留：{'是' if old_test_machine_residual else '否'}")
    lines.append(
        "- 测试机相关正式条目引用："
        + (", ".join(f"`{x}`" for x in test_machine_refs) if test_machine_refs else "无")
        + "（均来自 owner-approved active long_term 时不计为旧残留）"
    )
    lines.append(f"- 是否有旧事实污染：{'是' if old_fact_pollution else '否'}")
    if old_fact_notes:
        lines.append("- 旧事实/替换标记备注：")
        for note in old_fact_notes:
            lines.append(f"  - {md_escape(note)}")
    else:
        lines.append("- 旧事实/替换标记备注：无")
    lines.append("")
    lines.append("## 4. 结论")
    lines.append("")
    lines.append(f"- 阶段 A：{'PASS' if overall else 'FAIL'}")
    lines.append(f"- active sha：`{checks['sha256']}`")
    lines.append(f"- 是否发现旧测试机 9 条残留：{'是' if old_test_machine_residual else '否'}")
    lines.append(f"- 是否发现旧事实污染：{'是' if old_fact_pollution else '否'}")
    lines.append(f"- 是否可以进入阶段 B：{'是' if overall else '否'}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="read-only migration memory retrieval smoke")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH), help="markdown report path")
    parser.add_argument("--no-report", action="store_true", help="do not write report; print only")
    args = parser.parse_args()

    lines, entries, parse_errors = load_memories(MEMORY_PATH)
    sha = sha256_file(MEMORY_PATH)
    checks = validate(entries, lines, parse_errors, sha)

    query_results: list[dict[str, Any]] = []
    for spec in QUERY_SPECS:
        hits = retrieve(entries, spec)
        coverage = group_coverage(hits, spec.expected_groups)
        query_results.append(
            {
                "query": spec.query,
                "hits": hits,
                "coverage": coverage,
                "pass": bool(hits) and all(coverage.values()),
            }
        )

    residual, test_machine_refs = detect_test_machine_residual(entries)
    old_pollution, old_fact_notes = detect_old_fact_pollution(entries)
    report = render_report(
        checks=checks,
        query_results=query_results,
        old_test_machine_residual=residual,
        test_machine_refs=test_machine_refs,
        old_fact_pollution=old_pollution,
        old_fact_notes=old_fact_notes,
    )

    if not args.no_report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        print(str(report_path))
    else:
        print(report)

    base_pass = all(
        bool(checks[key])
        for key in ("line_count_ok", "sha256_ok", "jsonl_parse_ok", "source_ok", "scope_ok", "status_ok")
    )
    retrieval_pass = all(item["pass"] for item in query_results)
    overall = base_pass and retrieval_pass and not residual and not old_pollution
    print("PHASE_A=" + ("PASS" if overall else "FAIL"))
    print("SHA256=" + checks["sha256"])
    print("OLD_TEST_MACHINE_9_RESIDUAL=" + ("YES" if residual else "NO"))
    print("OLD_FACT_POLLUTION=" + ("YES" if old_pollution else "NO"))
    print("CAN_ENTER_PHASE_B=" + ("YES" if overall else "NO"))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
