from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .grounding import GroundingResult
from .query_router import StructuredMemoryQuery, detect_structured_memory_query
from .types import LongTermMemoryEntry, Scope


@dataclass(slots=True, frozen=True)
class RetrievalDiagnosticRecord:
    """C4 检索诊断条目。

    只暴露排序必要元数据与脱敏摘要预览，避免在日志里打印完整私密记忆。
    """

    id: str
    slot: str
    kind: str
    score: float
    matched_terms: tuple[str, ...]
    summary_preview: str


class MemoryRetriever:
    """长期记忆检索器。

    按 scope + 关键词 + 权重检索，默认不注入。
    不接 LLM，不改生产链路。
    """

    # 权重系数
    WEIGHT_SCOPE_EXACT = 5.0
    WEIGHT_SCOPE_PARTIAL = 2.0
    WEIGHT_KEYWORD_VALUE = 3.0
    WEIGHT_KEYWORD_SUMMARY = 2.0
    WEIGHT_KEYWORD_TAGS = 1.5
    WEIGHT_KEYWORD_SLOT = 1.0
    WEIGHT_KEYWORD_TERM = 0.5
    WEIGHT_RECENCY_HOURS = 0.02  # 每小时衰减

    QUERY_SPLIT_RE = re.compile(r"[\s,，。.!！?？、；;：:（）()【】\[\]《》<>\"'“”‘’/\\|]+")
    LONG_TERM_FACT_USAGE_GUARD = (
        "长期记忆使用约束：当用户问题与本段事实相关时，回答应优先使用其中关键事实，"
        "先说具体迁移/分工/关系事实，再少量补充；不要只给泛泛常识回答。"
    )
    DOMAIN_QUERY_TERMS = (
        "模型分工",
        "模型",
        "分工",
        "搬家路线",
        "搬家",
        "路线",
        "迁移路线",
        "迁移",
        "AstrBot",
        "NoneBot",
        "测试机同志",
        "测试机",
        "测试BOT",
        "测试bot",
        "小测试机",
        "nonebot测试机",
        "NoneBot测试机",
        "NoneBot 测试机",
        "先遣验证",
        "真机验证",
        "记住",
        "被记住",
        "值得",
        "贡献",
        "功臣",
        "加班默契",
        "加班",
        "结束了没",
        "1点",
        "一点",
        "23点",
        "二十三点",
    )
    TEST_MACHINE_QUERY_TRIGGERS = (
        "测试机同志",
        "测试机",
        "测试BOT",
        "测试bot",
        "小测试机",
        "nonebot测试机",
        "NoneBot测试机",
        "NoneBot 测试机",
    )
    TEST_MACHINE_ALIASES = (
        "测试机",
        "测试BOT",
        "测试bot",
        "小测试机",
        "先遣验证",
        "真机验证",
        "nonebot测试机",
        "NoneBot测试机",
        "NoneBot 测试机",
        "test_machine",
        "test machine",
        "test bot",
    )
    TEST_MACHINE_CONTRIBUTION_TERMS = ("被记住", "记住", "值得", "贡献", "功臣", "真机验证", "先遣测试")
    STOP_TERMS = {"我们", "为什么", "一下", "现在", "来说", "说一下", "要从", "搬到", "什么"}
    WEIGHT_CONFIDENCE = 1.0
    WEIGHT_SUPPORT_COUNT = 0.3

    # 检索预算
    DEFAULT_TOP_K = 3
    DEFAULT_CHAR_BUDGET = 500

    def retrieve(
        self,
        entries: list[LongTermMemoryEntry],
        *,
        query: str = "",
        session_id: str = "",
        user_id: str = "",
        group_id: str = "",
        top_k: int = DEFAULT_TOP_K,
        char_budget: int = DEFAULT_CHAR_BUDGET,
        grounding_result: GroundingResult | None = None,
    ) -> list[LongTermMemoryEntry]:
        """从传入的条目列表中按 scope + 结构化问句 + 权重检索。

        Args:
            entries: 待检索的全部长期记忆条目。
            query: 当前用户消息/查询文本。显式询问自身偏好时优先结构化 slot 查询。
            session_id: 当前会话 ID。
            user_id: 当前用户 ID。
            group_id: 当前群 ID。
            top_k: 返回最多条数。
            char_budget: 总字符预算（用于 render 阶段）。
            grounding_result: 可选 B2-C1 grounding/alias hint；默认 None 时保持旧行为。

        Returns:
            按相关性降序排列的条目列表；结构化 slot 命中时排在最前，
            未命中则保持原 C4 关键词/权重检索行为。
        """
        # 1. Scope 过滤
        scoped = self._filter_by_scope(entries, user_id=user_id, group_id=group_id)

        # 2. 显式问句优先走结构化 slot 查询；没命中再回退原语义/评分。
        structured_query = detect_structured_memory_query(query)
        structured_hits: list[LongTermMemoryEntry] = []
        if structured_query is not None:
            structured_hits = self._rank_structured_matches(scoped, structured_query, top_k=top_k)

        # 2.5 可选 B2-C1 grounding/alias hint。
        # 仅当调用方显式传入 resolved grounding_result 时生效；ambiguous/none 不硬选。
        grounding_hits = self._rank_grounding_matches(scoped, grounding_result, top_k=top_k)

        structured_keys = {self._entry_key(entry) for entry in structured_hits}
        grounding_keys = {self._entry_key(entry) for entry in grounding_hits}
        fallback_pool = [
            entry
            for entry in scoped
            if self._entry_key(entry) not in structured_keys and self._entry_key(entry) not in grounding_keys
        ]

        # 3. 打分排序（原 C4 fallback）
        scored = [
            (entry, self.score_entry(entry, query=query, user_id=user_id, group_id=group_id))
            for entry in fallback_pool
        ]
        scored.sort(key=lambda x: -x[1])
        fallback = [entry for entry, score in scored]

        # 4. top_k 截断：结构化命中永远在前；grounding hint 只在其后补位；
        # 未传 grounding_result 时等价原行为。
        if structured_hits or grounding_hits:
            return (structured_hits + grounding_hits + fallback)[:top_k]
        return fallback[:top_k]

    def retrieve_with_diagnostics(
        self,
        entries: list[LongTermMemoryEntry],
        *,
        query: str = "",
        session_id: str = "",
        user_id: str = "",
        group_id: str = "",
        top_k: int = DEFAULT_TOP_K,
        char_budget: int = DEFAULT_CHAR_BUDGET,
        grounding_result: GroundingResult | None = None,
    ) -> tuple[list[LongTermMemoryEntry], list[RetrievalDiagnosticRecord]]:
        """返回检索条目及脱敏诊断信息。

        这是 C4 调试用最小扩展：不改变 retrieve() 的原签名和返回类型，
        只对最终 retrieved entries 计算 id/slot/kind/score/matched_terms/summary_preview。
        """
        retrieved = self.retrieve(
            entries,
            query=query,
            session_id=session_id,
            user_id=user_id,
            group_id=group_id,
            top_k=top_k,
            char_budget=char_budget,
            grounding_result=grounding_result,
        )
        diagnostics = [
            self.build_diagnostic_record(entry, query=query, user_id=user_id, group_id=group_id)
            for entry in retrieved
        ]
        return retrieved, diagnostics

    def build_diagnostic_record(
        self,
        entry: LongTermMemoryEntry,
        *,
        query: str = "",
        user_id: str = "",
        group_id: str = "",
    ) -> RetrievalDiagnosticRecord:
        """为单条检索结果构建脱敏诊断记录。"""
        return RetrievalDiagnosticRecord(
            id=str(entry.id or ""),
            slot=str(entry.slot or ""),
            kind=str(entry.kind or ""),
            score=self.score_entry(entry, query=query, user_id=user_id, group_id=group_id),
            matched_terms=self._matched_terms(entry, query),
            summary_preview=self.sanitize_preview(entry.summary or entry.value, limit=96),
        )

    @classmethod
    def format_diagnostics(cls, diagnostics: list[RetrievalDiagnosticRecord], *, limit: int = 5) -> str:
        """格式化诊断记录用于日志；不输出完整私密记忆。"""
        if not diagnostics:
            return "(empty)"
        chunks: list[str] = []
        for item in diagnostics[: max(0, limit)]:
            terms = ",".join(item.matched_terms[:8]) if item.matched_terms else "-"
            chunks.append(
                f"id={item.id} slot={item.slot} kind={item.kind} "
                f"score={item.score:.4f} matched_terms=[{terms}] preview={item.summary_preview}"
            )
        if len(diagnostics) > limit:
            chunks.append(f"...(+{len(diagnostics) - limit})")
        return " | ".join(chunks)

    @classmethod
    def sanitize_preview(cls, text: Any, *, limit: int = 96) -> str:
        """日志预览脱敏：限长、折叠空白、隐藏长数字/路径/密钥形态。"""
        value = str(text or "").replace("\n", " ").replace("\r", " ")
        value = " ".join(value.split()).strip()
        if not value:
            return ""
        value = re.sub(r"(?<!\S)(?:[A-Za-z_][\w.-]*=)?/(?:[^\s/]+/){2,}[^\s]*", "<path>", value)
        value = re.sub(r"(?i)(sk-[a-z0-9_-]{8,}|token[=:][^\s]+|key[=:][^\s]+)", "<secret>", value)
        value = re.sub(r"(?<!\d)\d{5,12}(?!\d)", "<id>", value)
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 1)] + "…"

    def retrieve_structured(
        self,
        entries: list[LongTermMemoryEntry],
        *,
        query: str,
        user_id: str = "",
        group_id: str = "",
        top_k: int = DEFAULT_TOP_K,
    ) -> list[LongTermMemoryEntry]:
        """仅执行结构化 slot 查询。

        供测试/调试使用；仍然先走现有 scope 过滤，不绕过 private/group 隔离。
        """
        structured_query = detect_structured_memory_query(query)
        if structured_query is None:
            return []
        scoped = self._filter_by_scope(entries, user_id=user_id, group_id=group_id)
        return self._rank_structured_matches(scoped, structured_query, top_k=top_k)


    def score_entry(
        self,
        entry: LongTermMemoryEntry,
        *,
        query: str = "",
        user_id: str = "",
        group_id: str = "",
    ) -> float:
        """计算条目与查询/上下文的综合相关性分数。"""
        score = 0.0
        q = query.strip().lower() if query else ""

        # —— Scope 匹配分 ——
        if entry.scope == "private_user" and entry.scope_id == user_id:
            score += self.WEIGHT_SCOPE_EXACT
        elif entry.scope == "group_shared" and entry.scope_id == group_id:
            score += self.WEIGHT_SCOPE_EXACT
        elif entry.scope == "group_user":
            e_gid, e_uid = self._parse_group_user_scope(entry.scope_id)
            if e_gid == group_id and e_uid == user_id:
                score += self.WEIGHT_SCOPE_EXACT
            elif e_gid == group_id:
                score += self.WEIGHT_SCOPE_PARTIAL

        # —— 关键词匹配分 ——
        if q:
            score += self._keyword_match_score(entry, q)

        # —— 置信度分 ——
        score += entry.confidence * self.WEIGHT_CONFIDENCE

        # —— support_count 分（表示经过多次确认）——
        score += min(entry.support_count, 10) * self.WEIGHT_SUPPORT_COUNT

        # —— 时效性分（最近越新越高）——
        score += self._recency_score(entry)

        return round(score, 4)

    def render_prompt_section(
        self,
        entries: list[LongTermMemoryEntry],
        char_budget: int = DEFAULT_CHAR_BUDGET,
        query: str = "",
        structured_query: StructuredMemoryQuery | None = None,
    ) -> str:
        """将检索结果渲染为 prompt 小节。

        格式：
        [来自长期记忆的事实]
        说明：以下记忆描述的是当前用户/对话对象，不是助手自己的经历；回答用户关于自己偏好/习惯/信息的问题时，请用“你/用户/对方/漂♂总”等用户主语，不要改成“我”；不确定时可说“记忆里显示/你之前说过”，不要猜。
        若当前 query 被识别为第一人称记忆问句，会追加轻量歧义约束：直接按用户自己的记忆回答，不要反问是否在问助手。
        预算不足时优先保留较短等价说明。
        - <条目概要>（<类别>/<标签>）

        受 char_budget 约束，超出部分从尾部截断。
        """
        if not entries:
            return ""

        header = "[来自长期记忆的事实]"
        subject_guard = (
            "说明：以下记忆描述的是当前用户/对话对象，不是助手自己的经历；"
            "回答用户关于自己偏好/习惯/信息的问题时，请用“你/用户/对方/漂♂总”等用户主语，不要改成“我”；"
            "不确定时可说“记忆里显示/你之前说过”，不要猜。"
        )
        compact_subject_guard = "说明：记忆描述当前用户，不是助手经历；回答偏好/习惯/信息用“你/用户/漂♂总”，不要说成“我”；不确定说“你之前说过”。"
        minimal_subject_guard = "说明：记忆是当前用户的，不是助手经历；用“你/漂♂总”，不要说“我”。"

        detected_query = structured_query
        if detected_query is None and query:
            detected_query = detect_structured_memory_query(query)
        has_self_memory_query = detected_query is not None and detected_query.intent == "ask_self_memory"
        if has_self_memory_query:
            disambiguation_guard = (
                "第一人称问句约束：用户说“我喜欢/我平时/我晚上/我最喜欢...什么”等，是在询问用户自己的记忆；"
                "请直接根据记忆用“你/漂♂总”等用户主语回答，不要反问“是在问我吗”；"
                "只有明确说“你喜欢/你喝/你玩...”时，才理解为询问助手偏好。"
            )
            compact_disambiguation_guard = (
                "第一人称问句约束：用户问“我喜欢/我平时/我晚上...什么”是在问自己的记忆；"
                "直接用“你/漂♂总”回答，不要反问“是在问我吗”。"
            )
            minimal_disambiguation_guard = "第一人称问句约束：这是用户在问自己的记忆；用“你/漂♂总”直接回答，不要反问是不是问助手。"
            guards = (
                f"{subject_guard}{disambiguation_guard}",
                f"{compact_subject_guard}{compact_disambiguation_guard}",
                f"{minimal_subject_guard}{minimal_disambiguation_guard}",
            )
        else:
            guards = (subject_guard, compact_subject_guard, minimal_subject_guard)

        entry_lines: list[str] = []
        for entry in entries:
            tags_str = "/".join(entry.tags[:4]) if entry.tags else str(entry.kind)
            entry_lines.append(f"- {entry.summary}（{tags_str}）")

        lines = [header]
        remaining = char_budget - len(header) - 1

        first_line_len = len(entry_lines[0]) if entry_lines else 0
        selected_guard = ""
        for guard in guards:
            after_guard = remaining - len(guard) - 1
            if after_guard <= 0:
                continue
            if not first_line_len or after_guard - first_line_len - 1 > 0:
                selected_guard = guard
                break
        if not selected_guard:
            for guard in guards:
                if remaining - len(guard) - 1 > 0:
                    selected_guard = guard
                    break
        if selected_guard:
            lines.append(selected_guard)
            remaining -= len(selected_guard) + 1

        for line in entry_lines:
            if remaining - len(line) - 1 <= 0:
                break
            lines.append(line)
            remaining -= len(line) + 1

        return "\n".join(lines)


    def _rank_grounding_matches(
        self,
        entries: list[LongTermMemoryEntry],
        grounding_result: GroundingResult | None,
        *,
        top_k: int,
    ) -> list[LongTermMemoryEntry]:
        """按 B2-C1 grounding hint 轻量提权匹配。

        Safety:
        - 只读取调用方已经 scope-filter 后的 entries。
        - 只接受 status=resolved 的 hint。
        - ambiguous/none/model-less 状态不硬选，直接返回空。
        - 不修改 entry，不写库。
        """
        if grounding_result is None or grounding_result.status != "resolved":
            return []

        wanted_slots = tuple(dict.fromkeys(grounding_result.expanded_slots))
        slot_rank = {slot: idx for idx, slot in enumerate(wanted_slots)}
        entity_candidates = tuple(grounding_result.entity_candidates)
        if not wanted_slots and not entity_candidates:
            return []

        scored: list[tuple[LongTermMemoryEntry, float]] = []
        for entry in entries:
            if entry.status != "active":
                continue
            score = 0.0

            if entry.slot in slot_rank:
                score += 50.0 - slot_rank[entry.slot] * 5.0

            entry_value = self._canonicalize_entry_value(entry.value).lower()
            entry_kind = self._kind_from_slot_for_grounding(entry.slot, entry.kind)
            raw_value = str(entry.value or "").lower()
            for idx, candidate in enumerate(entity_candidates):
                canonical = str(candidate.canonical or "").lower()
                if not canonical:
                    continue
                candidate_kind = str(candidate.kind or "")
                if candidate_kind and entry_kind != candidate_kind:
                    continue
                if canonical in entry_value or entry_value in canonical:
                    score += 100.0 + candidate.confidence * 10.0 - idx
                    continue
                alias_hit = any(str(alias or "").lower() in raw_value for alias in candidate.aliases)
                if alias_hit:
                    score += 45.0 + candidate.confidence * 5.0 - idx

            if score <= 0:
                continue
            score += entry.confidence * self.WEIGHT_CONFIDENCE
            score += min(entry.support_count, 10) * self.WEIGHT_SUPPORT_COUNT
            score += self._recency_score(entry)
            scored.append((entry, round(score, 4)))

        scored.sort(
            key=lambda item: (
                -item[1],
                -item[0].support_count,
                -item[0].confidence,
                item[0].id,
            )
        )
        return [entry for entry, score in scored[:top_k]]

    @staticmethod
    def _canonicalize_entry_value(value: str) -> str:
        result = str(value or "").strip()
        for prefix in ("打", "玩", "喝", "吃", "看", "听"):
            if result.startswith(prefix) and len(result) > len(prefix):
                return result[len(prefix) :].strip()
        return result

    @staticmethod
    def _kind_from_slot_for_grounding(slot: str, fallback: str) -> str:
        if "game" in slot:
            return "game"
        if "drink" in slot:
            return "drink"
        if "food" in slot:
            return "food"
        if "music" in slot or "song" in slot:
            return "music"
        if "show" in slot or "anime" in slot:
            return "show"
        return fallback or "memory"

    def _rank_structured_matches(
        self,
        entries: list[LongTermMemoryEntry],
        structured_query: StructuredMemoryQuery,
        *,
        top_k: int,
    ) -> list[LongTermMemoryEntry]:
        """按结构化问句的 slot/kind 精准筛选并排序。"""
        if not structured_query.slots:
            return []

        slot_rank = {slot: idx for idx, slot in enumerate(structured_query.slots)}
        scored: list[tuple[LongTermMemoryEntry, float]] = []
        for entry in entries:
            if entry.status != "active":
                continue
            if structured_query.kind and entry.kind != structured_query.kind:
                continue
            if entry.slot not in slot_rank:
                continue

            # slot 精准命中给大额基础分，确保排在语义噪声前；同类内部再按
            # slot 顺序、置信度、support_count、时效性排序。
            score = 100.0 - slot_rank[entry.slot] * 10.0
            score += entry.confidence * self.WEIGHT_CONFIDENCE
            score += min(entry.support_count, 10) * self.WEIGHT_SUPPORT_COUNT
            score += self._recency_score(entry)
            scored.append((entry, round(score, 4)))

        scored.sort(
            key=lambda item: (
                -item[1],
                slot_rank.get(item[0].slot, 999),
                -item[0].support_count,
                -item[0].confidence,
                item[0].id,
            )
        )
        return [entry for entry, score in scored[:top_k]]

    def _entry_key(self, entry: LongTermMemoryEntry) -> tuple[str, str, str, str, str, str]:
        """检索结果去重键；id 为空时也能用结构字段兜底。"""
        return (
            str(entry.id or ""),
            str(entry.scope or ""),
            str(entry.scope_id or ""),
            str(entry.kind or ""),
            str(entry.slot or ""),
            str(entry.value or ""),
        )

    # ── 内部方法 ──────────────────────────────────────

    def _filter_by_scope(
        self,
        entries: list[LongTermMemoryEntry],
        *,
        user_id: str = "",
        group_id: str = "",
    ) -> list[LongTermMemoryEntry]:
        """按 scope 拦截：只返回当前上下文有权看到的条目。

        - private_user: 仅当 user_id 匹配且是私聊时可见
        - group_user: 仅当 group_id + user_id 均匹配
        - group_shared: 仅当 group_id 匹配
        """
        filtered: list[LongTermMemoryEntry] = []
        for entry in entries:
            if entry.status != "active":
                continue
            scope = entry.scope
            sid = entry.scope_id

            if scope == "private_user":
                if user_id and sid == user_id:
                    filtered.append(entry)
            elif scope == "group_shared":
                if group_id and sid == group_id:
                    filtered.append(entry)
            elif scope == "group_user":
                e_gid, e_uid = self._parse_group_user_scope(sid)
                if e_gid == group_id and e_uid == user_id:
                    filtered.append(entry)
        return filtered

    def _parse_group_user_scope(self, scope_id: str) -> tuple[str, str]:
        """从 'group_id:user_id' 格式解析出 group_id 和 user_id。"""
        parts = scope_id.split(":", 1)
        if len(parts) >= 2:
            return parts[0], parts[1]
        return scope_id, ""

    def _keyword_match_score(self, entry: LongTermMemoryEntry, query: str) -> float:
        """关键词/别名匹配评分。中文短窗用 deterministic query expansion 兜底。"""
        score = 0.0
        terms = self._query_terms(query)
        if not terms:
            return score

        query_norm = self._normalize_text(query)
        query_compact = self._compact_text(query)
        matches = self._match_terms_by_field(entry, terms)

        value_norm = self._normalize_text(entry.value)
        value_compact = self._compact_text(entry.value)
        if query_norm and (query_norm in value_norm or query_compact in value_compact):
            score += self.WEIGHT_KEYWORD_VALUE
        value_terms = matches["value"]
        if value_terms:
            score += (len(value_terms) / max(len(terms), 1)) * self.WEIGHT_KEYWORD_VALUE * 0.5
            score += min(len(value_terms), 6) * 0.7

        summary_norm = self._normalize_text(entry.summary)
        summary_compact = self._compact_text(entry.summary)
        if query_norm and (query_norm in summary_norm or query_compact in summary_compact):
            score += self.WEIGHT_KEYWORD_SUMMARY
        summary_terms = matches["summary"]
        if summary_terms:
            score += (len(summary_terms) / max(len(terms), 1)) * self.WEIGHT_KEYWORD_SUMMARY * 0.5
            score += min(len(summary_terms), 6) * 0.6

        tag_terms = matches["tags"]
        if tag_terms:
            score += self.WEIGHT_KEYWORD_TAGS
            score += min(len(tag_terms), 4) * 0.9

        slot_terms = matches["slot"]
        if slot_terms:
            score += self.WEIGHT_KEYWORD_SLOT
            score += min(len(slot_terms), 4) * 0.8

        all_matched = set().union(value_terms, summary_terms, tag_terms, slot_terms, matches["kind"])
        if all_matched:
            score += min(len(all_matched), 8) * self.WEIGHT_KEYWORD_TERM

        score += self._test_machine_alias_boost(entry, query, matches)
        return score

    def _query_terms(self, query: str) -> tuple[str, ...]:
        """把中文/中英混合 query 展开成可复现的短词与领域 alias。"""
        raw = str(query or "").casefold().strip()
        if not raw:
            return ()
        compact_query = self._compact_text(raw)
        terms: list[str] = []

        def add(term: str) -> None:
            cleaned = self._clean_term(term)
            if not cleaned or cleaned in self.STOP_TERMS:
                return
            if len(cleaned) <= 1 and not cleaned.isascii():
                return
            if cleaned not in terms:
                terms.append(cleaned)

        for chunk in self.QUERY_SPLIT_RE.split(raw):
            add(chunk)
        for token in re.findall(r"[a-z0-9_]+", raw):
            add(token)

        for term in self.DOMAIN_QUERY_TERMS:
            if self._compact_text(term) in compact_query:
                add(term)
                add(self._compact_text(term))

        if any(self._compact_text(trigger) in compact_query for trigger in self.TEST_MACHINE_QUERY_TRIGGERS):
            for alias in self.TEST_MACHINE_ALIASES:
                add(alias)
                add(self._compact_text(alias))
            # query “测试机同志为什么值得被记住”里“同志/为什么”等不应主导；
            # 但“值得/记住”应帮贡献类纪念记忆压过普通迁移事实。
            for term in self.TEST_MACHINE_CONTRIBUTION_TERMS:
                if self._compact_text(term) in compact_query or term in {"贡献", "功臣", "真机验证", "先遣测试"}:
                    add(term)

        return tuple(terms)

    def _clean_term(self, term: str) -> str:
        value = self._normalize_text(term)
        value = self.QUERY_SPLIT_RE.sub("", value)
        return value.strip("-_ ")

    def _normalize_text(self, text: Any) -> str:
        return " ".join(str(text or "").casefold().split())

    def _compact_text(self, text: Any) -> str:
        value = self._normalize_text(text)
        return self.QUERY_SPLIT_RE.sub("", value)

    def _field_contains_term(self, text: Any, term: str) -> bool:
        cleaned = self._clean_term(term)
        if not cleaned:
            return False
        text_norm = self._normalize_text(text)
        text_compact = self._compact_text(text)
        return cleaned in text_norm or self._compact_text(cleaned) in text_compact

    def _match_terms_by_field(self, entry: LongTermMemoryEntry, terms: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
        fields = {
            "value": entry.value,
            "summary": entry.summary,
            "tags": " ".join(entry.tags),
            "slot": entry.slot,
            "kind": entry.kind,
        }
        result: dict[str, tuple[str, ...]] = {}
        for field_name, field_text in fields.items():
            matched: list[str] = []
            for term in terms:
                if self._field_contains_term(field_text, term) and term not in matched:
                    matched.append(term)
            result[field_name] = tuple(matched)
        return result

    def _matched_terms(self, entry: LongTermMemoryEntry, query: str) -> tuple[str, ...]:
        terms = self._query_terms(query)
        if not terms:
            return ()
        matches = self._match_terms_by_field(entry, terms)
        ordered: list[str] = []
        for field_name in ("slot", "tags", "summary", "value", "kind"):
            for term in matches[field_name]:
                if term not in ordered:
                    ordered.append(term)
        return tuple(ordered)

    def _test_machine_alias_boost(
        self,
        entry: LongTermMemoryEntry,
        query: str,
        matches: dict[str, tuple[str, ...]],
    ) -> float:
        """测试机同志纪念 query 的最小 alias/score boost。"""
        query_compact = self._compact_text(query)
        if not any(self._compact_text(trigger) in query_compact for trigger in self.TEST_MACHINE_QUERY_TRIGGERS):
            return 0.0

        searchable = " ".join(
            [entry.value, entry.summary, entry.slot, entry.kind, " ".join(entry.tags)]
        )
        has_test_machine_hit = any(self._field_contains_term(searchable, alias) for alias in self.TEST_MACHINE_ALIASES)
        if not has_test_machine_hit:
            return 0.0

        boost = 3.0
        slot_tag_terms = set(matches["slot"]) | set(matches["tags"])
        if slot_tag_terms:
            boost += 2.0

        asks_remember_reason = any(term in query_compact for term in ("记住", "值得", "纪念"))
        if asks_remember_reason and any(
            self._field_contains_term(searchable, term) for term in self.TEST_MACHINE_CONTRIBUTION_TERMS
        ):
            boost += 2.0
        return boost

    def _recency_score(self, entry: LongTermMemoryEntry) -> float:
        """时效性加分：last_seen_at 距今越近越高。"""
        try:
            last_seen = datetime.fromisoformat(entry.last_seen_at)
        except (ValueError, TypeError):
            return 0.0
        now = datetime.now(timezone.utc).astimezone()
        delta_hours = (now - last_seen).total_seconds() / 3600
        if delta_hours < 0:
            return 1.0  # 未来时间戳
        # 指数衰减：最近几小时高分，逐渐降低
        return max(0.0, 1.0 - delta_hours * self.WEIGHT_RECENCY_HOURS)
