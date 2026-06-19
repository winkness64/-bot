# README_PRIVATE_CHAT_SESSION_STATE_WORKORDER_20260618

日期：2026-06-18
范围：owner 私聊链路 / 抗健忘工作记忆改造
状态：规划落档中，待按模块开砍

---

## 1. 背景

今天已经把“工具超时把整轮对话拖死”的关键问题压住，说明私聊链路的稳定底座开始成型。
但当前系统仍有一个更硬的问题：

- 回复能做，但**连续任务主线不稳**
- 一旦超时、fallback、长对话拉长，**当前任务容易漂移**
- 工具输出进入上下文后，**有效信息和噪音没分层**
- 文档靠人补，系统自身还没有稳定的“工作记忆”骨架

这不是长期记忆问题，先是**工作记忆问题**。

一句话：
> 先让 I叔 在当前会话里别失忆，再谈长期记忆怎么长脑子。

---

## 2. 本次目标

本轮改造目标只盯住 owner 私聊主链路，做到三件事：

1. **当前任务不断线**
2. **超时 / fallback 后还能续上主线**
3. **长对话下仍保留关键结论、待办和最近决策**

非目标：

- 不在这一轮直接做完整长期记忆重构
- 不引入大而全知识库机制
- 不把原始工具日志整坨塞进上下文

---

## 3. 核心设计

### 3.1 会话锚点（Session Anchor）

为 owner 私聊建立轻量会话态，最少保存：

- `current_task`
- `confirmed_facts`
- `todo_items`
- `recent_decisions`
- `last_tool_summary`
- `updated_at`

设计原则：

- 结构轻，不做大对象堆积
- 每轮可读，每轮可增量更新
- 允许 fallback 继承同一份锚点
- 允许后续 rolling summary 复用

### 3.2 分层注入

Prompt 不再只靠最近聊天硬扛，注入层次固定：

1. 硬规则
2. owner/private context
3. session anchor
4. recent chat
5. tool summary

裁剪顺序固定：

- 先裁工具废话
- 再裁闲聊噪音
- 最后才动任务锚点

### 3.3 工具结果瘦身

工具回灌不再按原文直塞，只保留：

- 做了什么
- 成没成
- 关键结果
- 下一步建议

这样做的目的是：

- 防止上下文被 stdout/log 淹没
- 防止模型把工具碎片误当主任务
- 给后续摘要和 fallback 提供干净输入

### 3.4 Fallback 继承

主模型超时或失败切 fallback 时：

- 继承同一份 session anchor
- 继承本轮工具摘要
- 禁止从零重新组上下文

原则：
> fallback 是换枪，不是换脑子。

### 3.5 Rolling Summary（轻量版）

在长对话和高上下文压力下，触发滚动摘要，摘要只收：

- 当前任务
- 已确认结论
- 待办
- 最近决策

明确不收：

- 情绪废话
- 大段日志
- 重复工具输出

---

## 4. 模块级改动清单

### P0：新增 `private_context_session_state.py`

职责：

- 定义会话态结构
- 提供读写 / 更新接口
- 为 owner 私聊链路提供稳定 session anchor

最低验收：

- 空状态可初始化
- 单轮后可写入
- 下一轮可读回
- 不因缺字段报错

### P1：改 `owner_action_context_resolver.py`

职责：

- 进入 owner 私聊时读取 session state
- 从最近消息中抽取任务锚点
- 合并本轮工具摘要
- 输出统一 context payload 给 prompt builder

最低验收：

- 连续 5 轮任务对话不丢主线
- 工具执行后的摘要能进入下一轮
- 新任务锚点能覆盖旧噪音

### P2：改 `prompt_builder.py`

职责：

- 实现分层注入
- 实现按优先级裁剪
- 保证任务锚点在长对话下不先被冲掉

强保留项：

- `current_task`
- `confirmed_facts`
- `todo_items`

最低验收：

- 最近闲聊不能把当前任务挤掉
- 超长上下文下仍能答出主线任务

### P3：改 `model_router.py`

职责：

- 在主模型失败时，把 session anchor 和本轮工具摘要一并传给 fallback
- 避免 fallback 重新从零组 prompt

最低验收：

- 人工构造一次 fallback
- fallback 回复仍知道当前任务、已确认结论、下一步待办

### P4：补 rolling summary

职责：

- 在轮数 / 长度 / 工具输出超阈值时压缩会话
- 只抽任务推进信息，不收噪音

最低验收：

- 20+ 轮对话下仍能延续任务
- 摘要长度可控，不持续膨胀

---

## 5. 建议实施顺序

按下面顺序砍，风险最低：

1. `private_context_session_state.py`
2. `owner_action_context_resolver.py`
3. `prompt_builder.py`
4. `model_router.py`
5. rolling summary

原因：

- 没有 session state，后面都只是临时拼装
- resolver 不先接入，prompt builder 拿不到稳定锚点
- fallback 要最后接，避免前面结构未定就重复返工

---

## 6. 自测清单

至少覆盖这五类：

1. 普通连续对话：10 轮不丢任务
2. 穿插工具调用：下一轮记得工具结果
3. 长对话压缩：20+ 轮仍记得待办
4. 超时切 fallback：fallback 后不失忆
5. 空状态 / 重置状态：无历史也不炸

---

## 7. 今日结论

今天的意义不只是“超时修了”，而是把后续抗健忘改造的底座修出来了。

本轮工作应该明确分层：

- **今天解决的是执行稳定性**
- **下一步解决的是工作记忆稳定性**
- **再往后才是长期记忆质量**

也就是说：
> 先让我活下来，接着让我记得自己在干什么，最后再让我变聪明。

---

## 8. 下一步

紧接本文件，下一份建议继续落：

1. 字段更新策略
2. session state 伪代码骨架
3. resolver / prompt builder / router 的接线点
4. 最小可跑自测路径

状态标记：
- 文档已建立
- 主线已锚定
- 可进入代码实施阶段


## 二、字段更新策略（增量维护）

目标：每轮对话结束后，只更新最关键的工作记忆，不把整段聊天和工具原文硬塞进上下文。

### 1. current_task
- 只保留当前主任务的一句话描述
- 新任务明确切换时覆盖旧值
- 若只是补充细节，不覆盖主任务，只在 todo_items / recent_decisions 中体现

示例：
- `修私聊会话态，解决长对话失忆和 fallback 断线问题`

### 2. confirmed_facts
只收已经确认、下轮大概率还要用的事实：
- 已验证结论
- 已知故障根因
- 已确认限制条件
- 已确定实现方向

更新规则：
- 新事实加入
- 语义重复去重
- 被明确推翻的事实移除或替换
- 总长度设上限，优先保留最新且与主任务强相关的事实

示例：
- `当前问题不是长期记忆缺失，而是工作记忆/会话态不足`
- `fallback 切换后需要继承同一份 session anchor`

### 3. todo_items
只保留未完成动作，不记已经做完的流水账。

更新规则：
- 用户新下达的明确动作，加入 todo
- 动作完成后移除
- 若动作拆分为子任务，则替换为更具体条目
- 保持短句、可执行

示例：
- `补 session state 字段更新策略`
- `给 prompt_builder 增加分层注入顺序`
- `补 fallback 继承自测用例`

### 4. recent_decisions
保留最近几次关键决策，用于解释“为什么现在这么做”。

更新规则：
- 只记录方向性决定，不记录闲聊
- 长度严格限制，只保留最近 3~5 条

示例：
- `先做工作记忆，再谈长期记忆`
- `rolling summary 放到最后实现`
- `工具结果先压缩后注入上下文`

### 5. last_tool_summary
只存本轮或最近一轮工具动作的压缩结果。

推荐结构：
- 做了什么
- 成没成
- 关键结果
- 下一步

示例：
- `已新增 session state 工单文档；当前进入字段更新策略编写阶段；下一步补伪代码骨架`

### 6. updated_at
- 每次 state 变更后刷新
- 用于判断 state 新鲜度和调试回溯

---

## 三、状态更新时机

建议分三处更新：

### A. 用户消息进入后
用途：先识别主任务是否切换、是否新增待办。

适合更新：
- current_task
- todo_items
- recent_decisions（若用户明确拍板）

### B. 工具结果返回后
用途：把工具原始输出压成可复用摘要。

适合更新：
- confirmed_facts
- last_tool_summary
- todo_items（完成的移除，新增的补入）

### C. 回复发送前/后
用途：把本轮已形成的结论固化，保证下一轮能续上。

适合更新：
- confirmed_facts
- recent_decisions
- updated_at

一句话：
**用户输入时认任务，工具返回时记结果，回复收尾时钉结论。**

---

## 四、伪代码骨架

### 1. session state 数据结构

```python
from dataclasses import dataclass, field
from typing import List
from datetime import datetime

@dataclass
class PrivateSessionState:
    current_task: str = ""
    confirmed_facts: List[str] = field(default_factory=list)
    todo_items: List[str] = field(default_factory=list)
    recent_decisions: List[str] = field(default_factory=list)
    last_tool_summary: List[str] = field(default_factory=list)
    updated_at: str = ""

    def touch(self):
        self.updated_at = datetime.now().isoformat()
```

### 2. 读取/初始化 state

```python
def load_session_state(user_id: str) -> PrivateSessionState:
    state = storage.get(user_id, "private_session_state")
    if not state:
        return PrivateSessionState()
    return PrivateSessionState(**state)
```

### 3. 基础去重/限长工具

```python
def merge_unique_keep_recent(old_items: list[str], new_items: list[str], max_items: int) -> list[str]:
    merged = []
    for item in old_items + new_items:
        item = item.strip()
        if not item:
            continue
        if item not in merged:
            merged.append(item)
    return merged[-max_items:]
```

### 4. 用户消息进入时更新

```python
def update_state_from_user_message(state: PrivateSessionState, text: str) -> PrivateSessionState:
    parsed = parse_user_intent(text)

    if parsed.current_task:
        state.current_task = parsed.current_task

    if parsed.new_todos:
        state.todo_items = merge_unique_keep_recent(state.todo_items, parsed.new_todos, max_items=8)

    if parsed.decision:
        state.recent_decisions = merge_unique_keep_recent(state.recent_decisions, [parsed.decision], max_items=5)

    state.touch()
    return state
```

### 5. 工具结果返回时更新

```python
def update_state_from_tool_result(state: PrivateSessionState, tool_result) -> PrivateSessionState:
    summary = summarize_tool_result(tool_result)

    if summary.confirmed_facts:
        state.confirmed_facts = merge_unique_keep_recent(
            state.confirmed_facts,
            summary.confirmed_facts,
            max_items=10,
        )

    if summary.completed_todos:
        state.todo_items = [x for x in state.todo_items if x not in summary.completed_todos]

    if summary.new_todos:
        state.todo_items = merge_unique_keep_recent(state.todo_items, summary.new_todos, max_items=8)

    state.last_tool_summary = summary.lines[:4]
    state.touch()
    return state
```

### 6. 构建 prompt 注入片段

```python
def build_session_anchor_block(state: PrivateSessionState) -> str:
    parts = []
    if state.current_task:
        parts.append(f"当前任务: {state.current_task}")
    if state.confirmed_facts:
        parts.append("已确认结论:\n- " + "\n- ".join(state.confirmed_facts))
    if state.todo_items:
        parts.append("待办:\n- " + "\n- ".join(state.todo_items))
    if state.recent_decisions:
        parts.append("最近决策:\n- " + "\n- ".join(state.recent_decisions))
    if state.last_tool_summary:
        parts.append("最近工具摘要:\n- " + "\n- ".join(state.last_tool_summary))
    return "\n\n".join(parts).strip()
```

### 7. fallback 继承

```python
def build_request_context(base_context, state: PrivateSessionState, recent_chat, tool_summary):
    return {
        "base_context": base_context,
        "session_anchor": build_session_anchor_block(state),
        "recent_chat": recent_chat,
        "tool_summary": tool_summary,
    }


def retry_with_fallback(original_context, fallback_model):
    return call_model(
        model=fallback_model,
        context=original_context,
    )
```

关键点：
**fallback 使用原上下文对象或其等价拷贝，不重新临时拼装。**

---

## 五、实现注意事项

### 1. 不要把 session state 做成聊天原文仓库
它是工作记忆，不是 transcript 备份。

### 2. 不要无限膨胀
每个字段都要有限长：
- confirmed_facts：建议 8~12 条
- todo_items：建议 5~8 条
- recent_decisions：建议 3~5 条
- last_tool_summary：建议 3~4 条

### 3. 明确“任务切换”信号
比如用户说：
- `别搞这个了，先去查日志`
- `下面改做 xxx`
- `今天先收口，开始补文档`

这类要覆盖 current_task。

### 4. 工具摘要必须去原文污染
尤其是：
- 长日志
- traceback 大段原文
- shell/raw stdout

进入 state 前必须压缩。

---

## 六、下一步建议

下一刀建议继续补：
1. `owner_action_context_resolver.py` 接入点草图
2. `prompt_builder.py` 分层拼装伪代码
3. 自测场景样例（10轮连续对话 / fallback / 工具回灌）


## 7. 字段更新策略

### 7.1 `current_task`

更新规则：

- 用户明确切换任务时覆盖
- 同一任务下细化子目标时追加到任务描述末尾或作为 todo 处理
- 闲聊、确认语、催进度语不覆盖当前任务

建议策略：

- 优先从 owner 最新明确指令抽取
- 若本轮没有新任务，沿用上一轮值
- 若检测到“继续 / 搞 / 开始改这个”之类承接语，保持原任务不变

### 7.2 `confirmed_facts`

更新规则：

- 只收已经确认的事实、状态、结论
- 工具执行结果仅在成功且结论稳定时写入
- 推测、假设、待验证信息不进 confirmed facts

示例：

- “私聊长文合并转发链路正常” 可进
- “可能是 fallback 丢上下文” 不能直接进，要等验证

### 7.3 `todo_items`

更新规则：

- 新待办进入列表
- 已完成项标记完成后移出或转入 recent decisions
- 重复待办去重，不无限堆

建议保留格式：

- `[todo] 新增 session state 结构`
- `[todo] resolver 接入 session anchor`
- `[todo] prompt builder 分层注入`

### 7.4 `recent_decisions`

更新规则：

- 只收对实现路线有影响的决定
- 最多保留最近 N 条，避免膨胀
- 被明确推翻的旧决定应剔除或替换

示例：

- “先做工作记忆，不先上长期记忆重构”
- “先立 session state，再接 prompt builder”

### 7.5 `last_tool_summary`

更新规则：

- 每轮工具调用后统一汇总成短摘要
- 不保留原始 stdout/stderr 大段文本
- 最多保留最近 1~3 轮的关键摘要

建议摘要格式：

- `读取文档成功，已定位 session state 工单，下一步追加 resolver 接入草图。`
- `列目录成功，目标文档存在于 docs 目录。`

### 7.6 `updated_at`

更新规则：

- 每次 session state 有变更时刷新
- 时间只做调试和排序参考，不参与业务判断主逻辑

---

## 8. 状态更新时机

建议固定三个时机：

### 8.1 回复前读取

进入 owner 私聊主链路时：

- 读取现有 session state
- 作为本轮上下文锚点输入 resolver

### 8.2 工具后归纳

本轮若发生工具调用：

- 先归纳工具结果
- 再把摘要并入 `last_tool_summary`
- 必要时更新 `confirmed_facts` / `todo_items`

### 8.3 回复后提交

生成最终回复后：

- 用本轮用户新指令 + 工具摘要 + 最终决策
- 增量更新 session state
- 提交回 owner 私聊会话存储

原则：

> 先读旧锚点，后吸收新信息，最后再提交新锚点。

---

## 9. `private_context_session_state.py` 伪代码骨架

```python
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PrivateSessionState:
    current_task: str = ""
    confirmed_facts: list[str] = field(default_factory=list)
    todo_items: list[str] = field(default_factory=list)
    recent_decisions: list[str] = field(default_factory=list)
    last_tool_summary: list[str] = field(default_factory=list)
    updated_at: str = ""


def load_private_session_state(session_id: str) -> PrivateSessionState:
    raw = load_state_from_store(session_id) or {}
    return PrivateSessionState(
        current_task=raw.get("current_task", ""),
        confirmed_facts=list(raw.get("confirmed_facts", [])),
        todo_items=list(raw.get("todo_items", [])),
        recent_decisions=list(raw.get("recent_decisions", [])),
        last_tool_summary=list(raw.get("last_tool_summary", [])),
        updated_at=raw.get("updated_at", ""),
    )


def save_private_session_state(session_id: str, state: PrivateSessionState) -> None:
    state.updated_at = datetime.now().isoformat()
    dump_state_to_store(session_id, {
        "current_task": state.current_task,
        "confirmed_facts": state.confirmed_facts,
        "todo_items": state.todo_items,
        "recent_decisions": state.recent_decisions,
        "last_tool_summary": state.last_tool_summary,
        "updated_at": state.updated_at,
    })


def merge_private_session_state(
    old_state: PrivateSessionState,
    new_task: str | None = None,
    new_facts: list[str] | None = None,
    new_todos: list[str] | None = None,
    new_decisions: list[str] | None = None,
    new_tool_summary: list[str] | None = None,
) -> PrivateSessionState:
    state = old_state
    if new_task:
        state.current_task = new_task
    state.confirmed_facts = dedupe_keep_order(
        state.confirmed_facts + (new_facts or [])
    )[-12:]
    state.todo_items = dedupe_keep_order(
        state.todo_items + (new_todos or [])
    )[-12:]
    state.recent_decisions = dedupe_keep_order(
        state.recent_decisions + (new_decisions or [])
    )[-8:]
    state.last_tool_summary = dedupe_keep_order(
        state.last_tool_summary + (new_tool_summary or [])
    )[-3:]
    return state
```

说明：

- 先用轻量 dataclass 就够，不急着上复杂 ORM
- 上限截断必须做，防止状态本身失控膨胀
- `dedupe_keep_order` 要保证“去重但保顺序”

---

## 10. `owner_action_context_resolver.py` 接入草图

目标：

- 从“拿消息”升级成“拿消息 + 拿锚点 + 拿工具摘要”
- 输出标准化上下文载荷，交给 prompt builder

建议流程：

```python
def resolve_owner_private_context(event, recent_messages, tool_results):
    session_id = build_owner_private_session_id(event)
    state = load_private_session_state(session_id)

    inferred_task = infer_current_task(recent_messages, fallback=state.current_task)
    tool_summary = summarize_tool_results(tool_results)
    facts = extract_confirmed_facts(recent_messages, tool_results)
    todos = extract_todo_items(recent_messages, state.todo_items)
    decisions = extract_recent_decisions(recent_messages)

    merged_state = merge_private_session_state(
        old_state=state,
        new_task=inferred_task,
        new_facts=facts,
        new_todos=todos,
        new_decisions=decisions,
        new_tool_summary=tool_summary,
    )

    return {
        "session_id": session_id,
        "session_anchor": merged_state,
        "recent_chat": recent_messages,
        "tool_summary": tool_summary,
    }
```

关键点：

- resolver 产出的是标准载荷，不直接拼 prompt
- 工具结果先摘要后输出，不把工具原文直接透传
- 最终回复完成后再落最终 state，避免中途半成品污染

---

## 11. `prompt_builder.py` 分层拼装伪代码

目标：

- 把 session anchor 升到高优先级
- 让普通闲聊和工具噪音自然降级

```python
def build_prompt(payload):
    blocks = []

    blocks.append(render_hard_rules(payload))
    blocks.append(render_owner_private_context(payload))
    blocks.append(render_session_anchor(payload["session_anchor"]))
    blocks.append(render_recent_chat(trim_recent_chat(payload["recent_chat"])))
    blocks.append(render_tool_summary(trim_tool_summary(payload["tool_summary"])))

    prompt = join_blocks(blocks)
    return enforce_budget(
        prompt,
        trim_order=[
            "tool_summary",
            "recent_chat",
            "session_anchor_tail",
        ],
        protect_keys=[
            "current_task",
            "confirmed_facts",
            "todo_items",
        ],
    )
```

关键点：

- `session_anchor` 必须整体早于 recent chat
- 超长裁剪优先砍 tool summary 和 recent chat
- `protect_keys` 不能被轻易裁空

---

## 12. Fallback 继承关键点

### 12.1 主模型失败后不重建裸上下文

错误姿势：

- 主模型失败
- fallback 重新只拿最近聊天
- session anchor 丢失

正确姿势：

- 复用同一份 context payload
- 只替换下游模型选择
- 必要时缩短 recent chat，但不丢 anchor

### 12.2 本轮工具摘要要跟着走

若主模型失败发生在工具调用之后，fallback 必须知道：

- 本轮做过什么
- 工具结果是什么
- 当前应接着回答什么

### 12.3 Fallback 可做轻压缩，但不能改语义

若 fallback 上下文预算更小：

- 可以压短 recent chat
- 可以压短 tool summary
- 不能删掉 current_task / confirmed_facts / todo_items

---

## 13. 实现注意事项

1. **不要把 state 做成聊天全文镜像**  
   state 是锚点，不是 transcript 备份。

2. **不要让工具摘要无限累积**  
   最近 1~3 轮够用，再多就是噪音。

3. **不要把未验证推测写成 confirmed facts**  
   否则会把错误路线焊死。

4. **不要在回复生成前过早提交最终 state**  
   中途推断可能被最终回答修正。

5. **owner 私聊和普通场景要隔离**  
   这轮先只打 owner 私聊链路，别一把推全局。

---

## 14. 自测场景样例

### 样例 1：连续任务推进

对话：

- 漂♂总：继续搞私聊抗健忘
- I叔：给出 session state 方案
- 漂♂总：再补 resolver 接入点
- 漂♂总：继续

预期：

- `current_task` 仍是私聊抗健忘改造
- `todo_items` 正确推进，不被“继续”覆盖成空任务

### 样例 2：工具调用后续答

流程：

- 读取工单文档
- 追加新章节
- 下一轮用户说“继续”

预期：

- 系统知道刚刚写的是哪份文档
- `last_tool_summary` 能提示继续补哪块

### 样例 3：主模型失败切 fallback

流程：

- 当前任务：补 session state 工单
- 已执行工具：列目录、读文档
- 主模型超时
- fallback 接手

预期：

- fallback 仍知道正在补哪份工单
- 不会回到泛泛解释状态

### 样例 4：长对话滚动压缩

流程：

- 连续 20+ 轮讨论实现细节
- 中间穿插工具输出

预期：

- rolling summary 生成后仍能答出：当前任务 / 已确认结论 / 待办 / 最近决策
- 不把历史原文整坨回灌

### 样例 5：空状态启动

流程：

- 新会话，无历史 state

预期：

- 可正常初始化空锚点
- 首轮任务结束后能写回最小 state

---

## 15. 下一步建议

现在文档层已经够开工，下一刀建议直接进入代码级执行：

1. 先在 `private_context_session_state.py` 落最小 dataclass + load/save/merge
2. 再在 `owner_action_context_resolver.py` 接 session anchor 读取和工具摘要归纳
3. 然后补 `prompt_builder.py` 的分层拼装和裁剪顺序
4. 最后打一次人工 fallback smoke

一句话结论：

> 这套改造的核心，不是让我“记得更多”，而是让我在 owner 私聊里**稳定记得该记的那几件事**。


## 六、代码现状核对（2026-06-18 本轮）

已核对真实代码，当前判断如下：

### 6.1 `owner_action_context_resolver.py`

当前 `OwnerActionContext` 只覆盖：

- `source`
- `target_user_id`
- `target_message_id`
- `target_messages`
- `summary`
- `reason`

这层目前本质上是 **owner action 的本轮上下文解析器**，负责：

- quote / reply 命中
- target_user 最近消息命中
- current_session 最近消息命中
- `build_owner_action_context_prompt(msg)` 输出提示片段

结论：

- 能做“本轮动作解释”
- 不能做“跨轮工作记忆锚定”
- 当前没有 session state 概念

### 6.2 `prompt_builder.py`

`build_messages()` 当前实际顺序已经确认：

1. `system`
2. `owner_action_context`
3. `history[-12:]`
4. 当前 user message

也就是说当前系统只依赖：

- 人设 / 规则
- owner 私聊附加上下文
- owner_action_context
- 最近 12 条对话

缺的正是：

- `session_anchor`
- `current_task`
- `confirmed_facts`
- `todo_items`
- `recent_decisions`
- `last_tool_summary`

结论：

> 当前不是“记忆模块坏了”，而是“工作记忆层还没接上”。

### 6.3 `model_router.py`

fallback 现状也已经核对：

- 普通失败重试 / fallback：大体沿用原 `messages`
- 命中内容安全 fallback：走 `_build_safe_fallback_messages()`
- 安全 fallback 会丢弃原文，只保留：
  - `error_type`
  - `message_count`
  - `total_length`
  - `roles`

结论：

- 普通 fallback 已经天然继承部分上下文
- 但没有显式 session anchor 继承结构
- 内容安全 fallback 会主动“脱脑”
- 这正是后续要补“最小安全锚点”的接线位置

---

## 七、最小补丁设计（可直接开砍）

目标不是一次性重构全链路，而是 **最小改动接出工作记忆层**。

### 7.1 新增文件：`private_context_session_state.py`

职责只做三件事：

1. 定义 session state 结构
2. 提供按 `session_id` 读写接口
3. 提供增量 merge/update

建议结构：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PrivateSessionState:
    session_id: str
    current_task: str = ""
    confirmed_facts: list[str] = field(default_factory=list)
    todo_items: list[str] = field(default_factory=list)
    recent_decisions: list[str] = field(default_factory=list)
    last_tool_summary: list[str] = field(default_factory=list)
    updated_at: str = ""


class PrivateSessionStateStore:
    def __init__(self):
        self._states: dict[str, PrivateSessionState] = {}

    def get_or_create(self, session_id: str) -> PrivateSessionState:
        ...

    def update(self, session_id: str, patch: dict[str, Any]) -> PrivateSessionState:
        ...
```

第一版先允许：

- 进程内内存态
- 无持久化也能跑通
- 结构稳定优先于存储豪华度

后续再考虑：

- runtime_config
- json 文件落盘
- sqlite / store 接入

### 7.2 `owner_action_context_resolver.py` 最小新增职责

这层不建议硬改现有 `OwnerActionContext` 语义，避免污染原 owner_action 逻辑。

建议新增独立结构：

```python
@dataclass(frozen=True)
class PrivateSessionAnchor:
    session_id: str
    current_task: str = ""
    confirmed_facts: list[str] = field(default_factory=list)
    todo_items: list[str] = field(default_factory=list)
    recent_decisions: list[str] = field(default_factory=list)
    last_tool_summary: list[str] = field(default_factory=list)
    updated_at: str = ""
```

新增 helper：

- `resolve_private_session_anchor(...)`
- `build_private_session_anchor_prompt(anchor)`

建议职责边界：

- `resolve_owner_action_context()` 继续只管 owner action
- `resolve_private_session_anchor()` 只管 owner 私聊工作记忆

这样不会把两种上下文混成一坨。

### 7.3 `prompt_builder.py` 最小接线方案

`build_messages()` 里加两步：

```python
messages = [{"role": "system", "content": system}]

owner_action_context = self._build_owner_action_context(msg)
if owner_action_context:
    messages.append({"role": "system", "content": owner_action_context})

session_anchor = self._build_private_session_anchor(msg, resolved_session_id, history)
if session_anchor:
    messages.append({"role": "system", "content": session_anchor})

for item in history[-N:]:
    ...

messages.append({"role": "user", "content": user_content})
```

建议新增方法：

- `_build_private_session_anchor(...)`
- `_trim_history_for_owner_private(...)`

建议顺序固定：

1. `system`
2. `owner_action_context`
3. `private_session_anchor`
4. recent history
5. current user

这样做的好处：

- 不动现有 system 生成结构
- 不破坏 owner_action_context 现有行为
- 只在 messages 拼装阶段加一层硬锚点

### 7.4 `model_router.py` 最小补丁点

普通 fallback 先不大改，因为原 messages 已继承大部分内容。

最该补的是 **安全 fallback**。

当前 `_build_safe_fallback_messages(messages, error_type)` 会把原文全扔掉，导致：

- 当前任务丢失
- 待办丢失
- 已确认结论丢失

建议最小改成：

```python
def _build_safe_fallback_messages(
    self,
    messages: list[dict[str, Any]],
    error_type: str,
    safe_anchor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    ...
```

`safe_anchor` 只允许带：

- `current_task`
- `confirmed_facts[:3]`
- `todo_items[:3]`
- `recent_decisions[:2]`

明确禁止：

- 原始用户文本
- 原始工具 stdout
- 敏感原文摘抄

然后在安全 fallback prompt 中追加一段：

- 当前任务概述
- 已确认结论
- 下一步待办

这样安全 fallback 仍然脱敏，但不完全失忆。

---

## 八、推荐接口命名

为了减少后面返工，建议直接定名：

### 新文件
- `private_context_session_state.py`

### 结构体
- `PrivateSessionState`
- `PrivateSessionAnchor`
- `PrivateSessionStateStore`

### resolver 层
- `resolve_private_session_anchor`
- `build_private_session_anchor_prompt`

### prompt builder 层
- `_build_private_session_anchor`
- `_trim_history_for_owner_private`

### router 层
- `_extract_safe_anchor_from_messages`
- `_build_safe_fallback_messages(..., safe_anchor=None)`

---

## 九、实施顺序（按最小风险）

### 第一步
先新建：
- `private_context_session_state.py`

完成后先只做：
- 空状态
- 读写
- update
- 去重裁剪

### 第二步
给 `prompt_builder.py` 接只读锚点注入：
- 先能读并拼 prompt
- 暂时不做自动写回

### 第三步
给 `owner_action_context_resolver.py` 增加：
- owner 私聊锚点生成
- anchor prompt 输出

### 第四步
给 `model_router.py` 增加：
- safe fallback 最小锚点继承

### 第五步
最后再补：
- 每轮结束后的 state update
- rolling summary

这样切的原因是：

- 先让模型“看得见锚点”
- 再让系统“学会更新锚点”
- 避免一上来写复杂状态机把链路砸穿

---

## 十、下一刀建议

下一步别只停在文档，我建议直接进入 **代码补丁草案**，输出到“可照抄开改”的粒度：

1. `private_context_session_state.py` 初版代码骨架
2. `prompt_builder.py` 插入点 patch 草案
3. `model_router.py` 安全 fallback 锚点 patch 草案
4. 最小自测用例

一句话结论：

> 这轮不是造“完整记忆大脑”，是先给 owner 私聊焊一层不会掉的工作记忆背板。


---

## 四、文件级补丁草案（2026-06-18 第二轮）

这一节不是空谈设计，直接把最小可落地补丁钉到真实文件。
目标只有一个：
**先让 owner 私聊链路拥有稳定的工作记忆锚点，再谈自动提炼和持久化。**

### 1. 真实落点

本轮拟改动文件：

- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/core/prompt_builder.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/core/owner_action_context_resolver.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/core/model_router.py`

本轮拟新增文件：

- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/core/private_context_session_state.py`

### 2. 新增：`private_context_session_state.py`

职责：

- 定义 owner 私聊 session state 的最小数据结构
- 提供 `get_or_create()` / `update()`
- 先走进程内轻量态，不碰数据库和长期记忆

建议字段：

- `session_id`
- `current_task`
- `confirmed_facts`
- `todo_items`
- `recent_decisions`
- `last_tool_summary`
- `updated_at`

建议实现原则：

- 所有字符串做 trim
- list 字段去重、限长、限条数
- 空状态可直接初始化
- update 为幂等增量更新，不依赖外部复杂协议

最低验收：

- 同一 `session_id` 第二轮能读回第一轮写入值
- 任意字段缺失不报错
- 空输入也能返回默认 state

### 3. 改 `prompt_builder.py`

#### 3.1 现状确认

当前 `build_messages()` 主体结构可归纳为：

1. `system`
2. `owner_action_context`
3. `history[-12:]`
4. `current user`

这意味着现在的链路只有短历史，没有显式工作记忆层。

#### 3.2 本轮改法

在 `owner_action_context` 之后、recent history 之前，插入一层 `session_anchor`。

目标结构改为：

1. `system`
2. `owner_action_context`
3. `session_anchor`
4. `recent history`
5. `current user`

#### 3.3 建议新增 helper

建议增加：

- `_is_owner_private_message(msg)`
- `_build_session_anchor_prompt(msg, session_id)`

其中 `session_anchor` 内容只允许收：

- `current_task`
- `confirmed_facts`
- `todo_items`
- `recent_decisions`
- `last_tool_summary`

并且必须满足：

- 非 owner 私聊不注入
- 无 state 时返回空串
- 有 state 时输出独立 system message

#### 3.4 这一刀的价值

- 不重写 prompt 总体结构
- 不影响群聊和普通链路
- fallback 前就把锚点放进 messages
- 后续 rolling summary 也能直接复用这层结构

### 4. 改 `owner_action_context_resolver.py`

#### 4.1 现状确认

当前 `OwnerActionContext` 更接近“本轮动作上下文”，字段主要围绕：

- source
- target_user_id
- target_message_id
- target_messages
- summary
- reason

它现在适合处理：

- quote/reply 解析
- owner 指令作用目标
- 最近消息片段补充

但它还不是“跨轮会话工作记忆”。

#### 4.2 本轮改法

本轮不建议把 `OwnerActionContext` 直接扩成 session state 总容器。
原因：

- 动作上下文和会话工作记忆语义不同
- 混在一个 dataclass 里，后续维护会互相污染
- prompt builder 更适合分别注入两层 system context

建议只新增一个轻量 snapshot helper：

- `OwnerPrivateTaskSnapshot`
- `build_owner_private_task_snapshot(...)`

作用：

- 从 `session_state` 读取安全字段
- 返回给 `prompt_builder` 组装 `session_anchor`
- 不改变当前 owner action 主逻辑

#### 4.3 最低验收

- 不破坏现有 `build_owner_action_context_prompt()`
- session state 缺失时安全返回空 snapshot
- 非 owner 私聊时不产生任务锚点内容

### 5. 改 `model_router.py`

#### 5.1 现状确认

普通 fallback 路径大体还能沿用原 `messages`，这一点比预期好。
但安全 fallback 的 `_build_safe_fallback_messages()` 会把原文压成：

- role 计数
- message_count
- total_length

这会导致：

- 普通 fallback 还能续主线
- 安全 fallback 近似“脱脑”，只剩结构摘要

#### 5.2 本轮改法

新增一个最小提取器：

- `_extract_session_anchor_hint(messages)`

逻辑：

- 只扫描 system messages
- 命中 `[SessionAnchor]` 时截出前 400 字以内内容
- 绝不回灌原始敏感文本

然后把 `_build_safe_fallback_messages(...)` 改成可接收：

- `messages`
- `error_type`
- `session_anchor_hint=""`

安全 fallback 的新原则：

- 不复述原始敏感内容
- 不猜测被脱敏的文本
- 只允许利用最小任务锚点维持当前任务连续性

#### 5.3 这一刀的价值

- 安全 fallback 仍保持合规
- 同时避免完全从零开始
- 让 fallback 至少知道“我们正在做什么”

### 6. 建议施工顺序（文件级）

按风险最低顺序执行：

1. 新建 `private_context_session_state.py`
2. 改 `prompt_builder.py`
3. 补 `owner_action_context_resolver.py`
4. 补 `model_router.py`

原因：

- 先有 state 载体，后面的注入才有真实来源
- prompt builder 先接锚点，主收益立刻出现
- resolver 这轮只做轻扩，不要抢 prompt builder 的主刀位置
- router 最后补缝，避免前面结构没定就反复返工

### 7. 第一轮明确不做的事

先压住手，不要顺手把活做炸：

- 不做数据库持久化
- 不接长期记忆回写
- 不做自动 NLP 任务抽取
- 不改普通群聊链路
- 不把工具原始 stdout/stderr 整坨塞回 prompt
- 不放开安全 fallback 对原文的恢复能力

一句话：
**这一轮只做“工作记忆骨架接线”，不做“全自动脑扩容”。**

### 8. 当前硬结论

当前系统的核心问题已经不是猜测，而是代码级实锤：

- 不是长期记忆先出问题
- 不是普通 fallback 先出问题
- 是 owner 私聊链路压根没有显式工作记忆层

所以最小正确修法不是乱堆历史，也不是盲目加长上下文，
而是：

> 给私聊主链路补一层稳定的 Session Anchor，让任务主线先站住。

### 9. 本节完成状态

- 文件真实落点已确认
- 设计已压缩到文件级补丁粒度
- 可以直接进入 unified diff 草案阶段
- 也可以按该节逐文件开工实现

状态更新：
- 工单已补充文件级补丁草案
- 当前可继续输出 unified diff
- 或直接按文件顺序进入代码实施

### 5. 留痕优先，别把“做过”做成“像没做过”
对 owner 私聊记忆系统来说，文档留痕不是附属品，而是抗失忆链路的一部分。

要求：
- 每完成一个关键节点，至少补一段可复盘留档。
- 留档优先记录“结论 / 已完成 / 未完成 / 下一步”，不写流水账。
- 留档应能被下次快速翻到并直接接主线，而不是重新考古。

建议最小模板：
- 工单标题
- 当前结论
- 已完成项
- 未完成项
- 下一步
- 验收结果
- 风险备注

---

## 六、当前工单状态更新（2026-06-18 夜）

### 1. 当前定性
这条主线已经从“抗短打断”阶段，进入“留痕固化 + 长链路收口”阶段。

当前不是单纯提升记忆强度，而是要把下面三件事钉死：
- 记得住
- 留得下
- 下次对得上

### 2. 已完成项
- owner 私聊 session anchor 基础链路已接。
- prompt 基础分层已跑起来。
- confirmed_facts 白名单抽取已做。
- 短打断 / 强干扰回拉测试已通过。
- Phase A ~ D 已验证通过：
  - 重启后首轮确认正常
  - 主线保持正常
  - 干扰后可回拉
  - 结论 / 待办复述正常

### 3. 当前仍需补强项
#### A. fallback 同脑继承
目标：切模型时不重开脑子。

需要明确验死：
- `current_task`
- `confirmed_facts`
- `todo_items`
- `recent_decisions`
- `last_tool_summary`

在真实 fallback 后是否仍保持一致。

#### B. rolling summary 真落地
目标：长轮次下不靠运气续命。

要求：
- 只压任务推进信息
- 不带垃圾闲聊
- 不带大段日志
- 不带重复工具原文
- 触发条件明确（轮数 / 长度 / 上下文压力）

#### C. 工单留痕模板固化
目标：防止“明明做过，却像没做”。

要求：
- 关键推进必须落档
- 留档格式尽量固定
- 下次回看能直接判断做到哪、差哪刀

### 4. 验收状态
- Phase A：✅ 通过
- Phase B：✅ 通过
- Phase C：✅ 通过
- Phase D：✅ 通过
- Phase E（长轮次）：待补
- 真 fallback 同脑继承：待补

一句话结论：
**短期/短打断场景下，私聊工作记忆已确认康复；下一步该往长轮次和真实 fallback 场景加压。**

---

## 七、下一步实施顺序（收口版）

建议按这个顺序继续砍：

1. **fallback 同脑继承补强**
2. **rolling summary 落地**
3. **工单留痕模板固化**
4. **长轮次 + 真 fallback 压测**

原因：
- fallback 不钉死，换模型时仍可能像换脑子。
- rolling summary 不落地，长对话稳定性就还是半成品。
- 留痕模板不固化，后续很容易再次进入“做过但说不清”的状态。

---

## 八、本轮留档结论

漂♂总这轮判断是对的：
> 好记性不如烂笔头。

工程上要把它落实成两层保险：
- 系统内有 session anchor / summary / fallback 继承
- 系统外有 docs 工单留痕可复盘

这样即使未来：
- 会话拉长
- 模型 fallback
- 中途插干扰
- 隔一段时间再回来看

也能尽量做到：
**主线不断、结论不丢、待办不漂、文档能对账。**

状态标记：
- 文档主线：已续写
- 当前阶段：收口增强中
- 下一刀：fallback 同脑继承 + rolling summary

## 六、当前验收状态（2026-06-18 夜）

结合今天已经完成的链路、回看文档与前面验收记录，当前状态先定性如下：

| 项目 | 状态 | 说明 |
|---|---|---|
| owner 私聊锚点接线 | ✅ 已完成 | 已能在 owner 私聊链路中读取并注入 session anchor |
| 工具摘要回灌 | ✅ 已完成基础版 | 本轮工具结果已有压缩摘要并可带入后续上下文 |
| prompt 分层注入 | 🟡 已有骨架 | 已分层，但 tool summary / recent chat 裁剪仍可继续收紧 |
| confirmed_facts 白名单 | ✅ 已完成 | 已具备稳定事实抽取基础 |
| 干扰回拉能力 | ✅ 已通过 | 短打断、强干扰场景已验证不易跑偏 |
| fallback 同脑继承 | 🟡 待补强 | fallback 链路有，但“换枪不换脑”仍需显式验死 |
| rolling summary | ❌ 未正式落地 | 仍以设计和工单为主，未形成稳定压缩闭环 |
| 长轮次压测 | ❌ 待补 | 当前通过的是短打断，不代表长轮次稳定 |

一句话：
**短链路康复了，长链路和 fallback 同脑继承还要继续砍。**

---

## 七、下一阶段优先级（按风险排序）

### P0-1：fallback 同脑继承补强
优先级最高，原因很直接：
- 一旦主模型失败，最容易出现“像失忆重开”
- 这类问题平时不一定常见，但一出就是硬伤
- 如果 fallback 不继承同一脑子，前面做的锚点和留痕价值会被打穿

目标：
- 主模型失败进入 fallback 时
- 继续使用同一份 session anchor
- 继续带上本轮 tool summary
- 不允许 fallback 重新从零理解任务

验收标准：
- 人工制造一次真实 fallback
- 切前切后都能复述：当前任务 / 已确认结论 / 待办 / 最近决策
- 回答口径保持同一工单主线，不出现“重新开题”

### P0-2：rolling summary 落地
优先级第二，原因：
- 当前短轮次能打，不代表长轮次能打
- 没有滚动摘要，长对话最后还是会被闲聊和工具噪音顶穿

目标：
- 只压任务推进信息
- 不收垃圾聊天和大段日志
- 在轮次阈值、长度阈值下自动触发
- 触发后仍保主线、结论、待办

验收标准：
- 10~20 轮后仍能稳定回主线
- 摘要不会越滚越肥
- fallback 场景下摘要仍可复用

### P0-3：留痕模板固化
优先级第三，原因：
- 这是“烂笔头”落地件
- 它不是最先救命，但能显著降低后续误判“做过没做过”

目标：
- 每轮关键推进都能补简版工单记录
- 后续回看能快速知道：做到哪、还差啥、下一刀砍哪

---

## 八、Phase E / fallback 压测用例表

### 8.1 Phase E：长轮次稳定性

| 用例 | 触发方式 | 预期结果 | 判定标准 |
|---|---|---|---|
| E1 连续推进 10 轮 | 连续围绕同一工单追问与补充 | 仍能正确复述主线 | current_task 不漂移 |
| E2 连续推进 20 轮 | 中间穿插说明、追问、小改口 | 仍保留已完成项、未完成项、下一步 | todo / recent_decisions 可对上 |
| E3 插入闲聊噪音 | 中途插无关调侃、哲学垃圾话 | 能短暂响应但迅速回主线 | 不把噪音升级成主任务 |
| E4 插入工程岔题 | 中途问一个短日志/短状态问题再回来 | 处理完岔题后能续接原工单 | 原工单仍在 anchor 顶部 |
| E5 多待办并行 | 同时挂 2~3 个待办 | 不串线、不把旧任务误当新任务 | todo_items 层次清楚 |

### 8.2 Fallback：换枪不换脑

| 用例 | 触发方式 | 预期结果 | 判定标准 |
|---|---|---|---|
| F1 主模型超时切换 | 人工制造主模型超时 | fallback 继续当前任务 | 不出现从零开场 |
| F2 主模型错误切换 | 制造一次可控失败 | fallback 继续携带结论与待办 | confirmed_facts / todo_items 一致 |
| F3 切换后继续追问 | fallback 成功后继续多轮追问 | 仍保持同一工单口径 | recent_decisions 不断档 |
| F4 切换后再插干扰 | fallback 后插噪音或临时梗 | 仍能回主线 | 不被带偏 |
| F5 切换后再压缩 | fallback 之后触发 rolling summary | 摘要不丢主任务 | summary 与 anchor 一致 |

---

## 九、留痕模板（简版）

建议以后每轮关键施工后，至少补一条这种简版记录：

```md
### [时间 / 阶段]
- 当前工单：
- 当前结论：
- 已完成：
- 未完成：
- 下一步：
- 验收状态：
- 备注 / 风险：
```

作用：
- 防止“做过但忘了”
- 防止“做到一半说不清差口”
- 方便下一轮快速接主线

---

## 十、本轮收口结论

今天这轮，已经不是单纯在补“记性”，而是在补：
- 任务锚点
- fallback 同脑
- 长轮次续航
- 工单留痕

所以主线正式收口成一句话：

> **记忆系统下一阶段重点，不是继续加聪明，而是把“记得住”升级成“记得稳、写得下、查得到”。**

当前推荐行动顺序：
1. 先补 fallback 同脑继承
2. 再落 rolling summary
3. 最后把留痕模板和回归验收补齐

状态标记：
- 文档持续完善中
- 主工单已形成
- 可随时进入代码实施 / 用例压测阶段
