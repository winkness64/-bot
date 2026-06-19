from __future__ import annotations

from typing import Any


PLAN_ONLY_CLASSIFIER_PROMPT = """你是意图分类器，只分析用户输入属于哪种模式，**只输出一个词**。

模式：
- plan_only：用户要求方案/分析/评估/思路，不要求实际执行。
  典型说法："先不动手""先说想法""暂时别改先评估""假如让你做会怎么做""帮我分析一下风险"
  "说说思路""如果做的话大概什么方案""先评估""给个计划""有什么坑"
- execute：用户要求实际执行/行动/工具调用。
  典型说法："帮我查""重启""写入""执行""跑一下""把那个文件改了""部署""看日志""列目录"
  "用 python 算""打包"
- clarify：用户意图模糊，无法判断；或同时包含 plan_only 和 execute；或只是一句闲聊。

只输出一个词：plan_only、execute 或 clarify。"""

PLAN_ONLY_SYSTEM_PROMPT = """你是秧秧，正在和漂♂总私聊。漂♂总要求你先出方案，不要动手执行。

规则：
- 只输出方案/分析/评估/思路，不要调用任何工具。
- 回复用自然语言，像聊天一样，不要套模板。
- 可以分步骤、列要点，但要像在跟漂♂总说话。
- 如果对需求有疑问，可以先澄清再出方案。
- 不要输出 tool_call、JSON 或工具调用。
- 如果方案涉及具体文件路径或目录，不要编造路径；用概括说法。"""

CLARIFY_REPLY = "漂♂总，我没太拿准你的意思——是想让我先出个方案分析一下，还是直接动手做？你先告诉我方向，我再继续。"


PLAN_ONLY_FAST_KEYWORDS = (
    "先不动手", "先说想法", "先评估", "先分析", "先出方案", "先说说",
    "暂时别改", "暂时不要", "先别动",
    "假如让你做", "如果让你做", "假设让你",
    "说说思路", "有什么方案", "有什么风险", "给个计划", "给个方案",
    "评估一下", "分析一下", "评估风险",
    "不要动手", "不要执行", "只出方案",
    "plan only", "只规划", "只分析",
)

def _fast_plan_only_precheck(user_text: str) -> str | None:
    """快速关键词预检。返回 None 表示需要 LLM 分类。
    
    用关键词快速识别 plan_only 和 execute，减少不必要的 LLM 调用。
    但模糊情况（同时有 plan_only 和 execute 关键词）返回 None 走 LLM。
    """
    text = str(user_text or "").strip().lower()
    if not text:
        return "execute"
    
    has_plan_only = any(marker in text for marker in PLAN_ONLY_FAST_KEYWORDS)
    
    # Explicit execute markers that contradict plan_only
    execute_markers = ("帮我查", "帮我读", "帮我写", "帮我列", "帮我打包",
                       "帮我看", "查一下", "列一下", "读一下",
                       "重启", "写入", "追加", "执行", "跑一下",
                       "看日志", "列目录", "打包",
                       "帮我跑", "帮我执行", "帮我重启",
                       "kill", "stop", "start", "restart",
                       "systemctl", "journalctl",
                       "看下", "看看", "查查", "列出来",
                       "有哪些模型", "可用模型", "启用模型",
                       "切换", "切到", "切模型", "切私聊", "切群聊", "模型到", "模型切",
                       "启用", "禁用",
                       "查看", "显示", "列出", "当前",
                       "查询", "测试")
    has_execute = any(marker in text for marker in execute_markers)
    
    if has_plan_only and not has_execute:
        return "plan_only"
    if has_execute and not has_plan_only:
        return "execute"
    # Both or neither: need LLM
    return None


async def classify_owner_intent(
    user_text: str,
    model_router: Any,
    tier: str = "v4_flash",
    *,
    session_id: str | None = None,
    channel: str = "",
) -> str:
    """用关键词预检 + LLM 联合判断 owner 意图模式。

    Returns one of: "plan_only", "execute", "clarify".
    Falls back to "execute" on any error.
    """
    if not user_text or not str(user_text).strip():
        return "execute"

    # Fast keyword pre-check
    fast_result = _fast_plan_only_precheck(user_text)
    if fast_result is not None:
        return fast_result

    # LLM classifier for ambiguous cases
    try:
        response_text, _actual_tier = await model_router.call(
            tier,
            _classifier_messages(str(user_text or "")),
            temperature=0.0,
            session_id=session_id,
            tools=None,
            tool_choice="none",
            channel=channel,
            timeout_bucket="progress",
            interaction_phase="plan_only_classify",
            allow_streaming=False,
        )
    except Exception:
        return "execute"

    return parse_gate_result(response_text)


def parse_gate_result(text: str) -> str:
    """Parse classifier output into one of plan_only/execute/clarify."""
    cleaned = str(text or "").strip().lower()
    # Exact match
    for mode in ("plan_only", "execute", "clarify"):
        if cleaned == mode:
            return mode
    # Fuzzy match: prefer plan_only over execute if both appear
    if "plan_only" in cleaned or "plan" in cleaned:
        return "plan_only"
    if "clarify" in cleaned:
        return "clarify"
    if "execute" in cleaned or "exec" in cleaned:
        return "execute"
    # Default: fall through to execute (safe)
    return "execute"


def _classifier_messages(user_text: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": PLAN_ONLY_CLASSIFIER_PROMPT},
        {"role": "user", "content": str(user_text or "")},
    ]


def plan_only_messages(user_text: str) -> list[dict[str, Any]]:
    """Build messages for plan_only mode: no tools, just output a plan."""
    return [
        {"role": "system", "content": PLAN_ONLY_SYSTEM_PROMPT},
        {"role": "user", "content": str(user_text or "")},
    ]
