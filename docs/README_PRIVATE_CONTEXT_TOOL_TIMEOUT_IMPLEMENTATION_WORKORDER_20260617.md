# README_PRIVATE_CONTEXT_TOOL_TIMEOUT_IMPLEMENTATION_WORKORDER_20260617.md

## 1. 目的
在不直接大改主骨架的前提下，为“私聊偶发断片 / 多工具后收口漂移 / 模型超时后语义重置”问题提供**模块级改动点清单、配置开关设计、灰度步骤、回滚点**。

本单承接上一份方案文档：
- `docs/README_PRIVATE_CONTEXT_TOOL_TIMEOUT_REMEDIATION_PLAN_20260617.md`

本单聚焦：
1. 改哪些模块；
2. 每个模块怎么改；
3. 先加哪些配置开关；
4. 如何灰度；
5. 如何回滚；
6. 如何验收。

---

## 2. 现状依据（按真实文件核对）
本次施工单基于以下模块现状：

### 2.1 Prompt 组装入口
- `src/plugins/yangyang/core/prompt_builder.py`

观察到：
- `PromptBuilder.build_system()` 负责拼装 system prompt；
- `PromptBuilder.build_messages()` 负责拼装 messages；
- 当前 system 侧已注入：人格、真实时间、owner private context、记忆、知识；
- 适合在这里插入“任务摘要 / 上下文注入观测 / 工具回灌瘦身后的统一入口”。

### 2.2 模型路由与回退入口
- `src/plugins/yangyang/core/model_router.py`

观察到：
- `ModelRouter.TIERS` 已有 tier 默认 timeout / cooldown；
- 已存在 fallback 记录字段：
  - `last_call_fallback_used`
  - `last_call_fallback_from`
  - `last_call_fallback_to`
  - `last_call_fallback_reason`
  - `fallback_history`
  - `fallback_stats`
- 适合在这里补“按轮次类型区分 timeout / fallback 观测 / 失败后收口策略标记”。

### 2.3 Owner 上下文解析器
- `src/plugins/yangyang/core/owner_action_context_resolver.py`

观察到：
- 当前有 `OwnerActionContext.summary` 和 `reason`；
- `build_owner_action_context_prompt()` 里仍存在“漂♂总指令上下文”字样；
- 当前更偏一次性 recent message 抽取，不是面向“多轮任务锚点常驻”。

### 2.4 运行时配置默认值
- `src/plugins/yangyang/admin/runtime_config.py`

观察到：
- 已有 memory / toolbox / timeout 等大量 runtime config 默认项；
- 当前默认存在：
  - `memory_short_term_capture_enabled = False`
  - `memory_prompt_injection_enabled = False`
  - `memory_prompt_char_budget = 4800`
  - `memory_prompt_short_term_item_limit = 16`
- 适合在这里增补新开关，走“默认关闭、手动灰度开启”。

---

## 3. 模块级施工项总览

| 编号 | 模块 | 目标 | 风险 | 灰度建议 |
|---|---|---|---|---|
| A1 | runtime_config.py | 增加新配置开关 | 低 | 先加默认值，不启用 |
| A2 | prompt_builder.py | 增加上下文分层注入与观测 | 中 | 私聊 owner 定向灰度 |
| A3 | 新增 context/session state 模块 | 保存 rolling summary / 任务锚点 | 中 | 先内存，后轻量落盘 |
| A4 | owner_action_context_resolver.py | 清理旧称呼，增强任务摘要输入 | 低 | 一次到位 |
| A5 | model_router.py | 区分 timeout/fallback 策略与观测 | 中 | 只开观测，再开行为 |
| A6 | 工具回灌瘦身入口 | 减少日志/长文本污染主 prompt | 中 | 先 owner 工具链灰度 |
| A7 | tests | 补回归测试与 smoke 用例 | 低 | 随改随补 |

---

## 4. 具体改动点

## A1. 运行时配置：先补开关，不直接开行为
文件：
- `src/plugins/yangyang/admin/runtime_config.py`

### A1-1. 新增配置项
建议新增以下默认值，全部默认保守：

```python
"private_context_observability_enabled": False,
"private_context_observability_sample_owner_only": True,
"private_context_observability_log_path": "logs/private_context_observability.jsonl",

"private_context_task_anchor_enabled": False,
"private_context_task_anchor_char_budget": 600,
"private_context_task_anchor_turn_ttl": 12,

"private_context_rolling_summary_enabled": False,
"private_context_rolling_summary_char_budget": 500,
"private_context_rolling_summary_update_min_turns": 2,
"private_context_rolling_summary_persist_enabled": False,
"private_context_rolling_summary_state_path": "data/private_context_session_state.json",

"private_context_recent_history_item_limit": 12,
"private_context_recent_history_char_budget": 2200,
"private_context_hard_rules_char_budget": 1200,
"private_context_tool_result_char_budget": 900,

"private_context_tool_result_summary_enabled": False,
"private_context_tool_result_error_only_default": True,

"private_context_timeout_strategy_enabled": False,
"private_context_timeout_first_reply_seconds": 90,
"private_context_timeout_tool_followup_seconds": 150,
"private_context_timeout_longform_seconds": 180,

"private_context_fallback_observability_enabled": False,
"private_context_fallback_soft_handoff_enabled": False,

"private_context_owner_only_gray_enabled": True,
```

### A1-2. 设计原则
- **默认不改变线上行为**；
- 先把所有开关补齐，便于后续灰度；
- 日志路径与状态路径统一纳入 runtime config，避免硬编码散落。

### A1-3. 风险
- 基本无功能风险；
- 主要风险是配置项过多，需要文档同步。

---

## A2. PromptBuilder：把“最近消息堆叠”改成分层注入
文件：
- `src/plugins/yangyang/core/prompt_builder.py`

### A2-1. 新增注入层次
建议把 prompt 注入明确拆为四层：

1. **硬规则层**
   - owner 私聊规则
   - 当前人格规则
   - 用户明确修正过的称呼/禁忌
   - 不参与普通 recent 裁剪

2. **任务锚点层**
   - 当前任务目标
   - 已确认结论
   - 明确待办
   - 不随工具结果波动

3. **最近对话层**
   - 最近若干轮 user/assistant
   - 控制条数和字符预算

4. **工具摘要层**
   - 只放结论、错误、状态、下一步字段
   - 不直接塞完整 stdout/stderr/log chunk

### A2-2. 代码层建议
在 `PromptBuilder` 内新增/拆分如下辅助函数：
- `_build_hard_rules_context(...)`
- `_build_task_anchor_context(...)`
- `_build_recent_history_context(...)`
- `_build_tool_result_context(...)`
- `_emit_private_context_observability(...)`

目标不是大改外部接口，而是在 `build_system()` / `build_messages()` 内部分层拼接。

### A2-3. 任务锚点内容建议
任务锚点统一格式：

```text
[CurrentTaskAnchor]
- 当前任务：...
- 已确认：...
- 未完成：...
- 禁忌/限制：...
- 最近决定：...
```

这样模型在多工具之后还有固定抓手，不容易“查着查着忘了为什么查”。

### A2-4. 观测日志建议
当 `private_context_observability_enabled=true` 时，记录：
- session_id
- channel
- sender_uid（必要时脱敏/最小化）
- recent_history_items_used
- hard_rules_chars
- task_anchor_chars
- tool_result_chars
- total_context_chars
- dropped_sections
- dropped_chars_estimate
- fallback_used
- timeout_bucket

写入：
- `logs/private_context_observability.jsonl`

### A2-5. 风险
- 如果直接放开预算，可能拖长首答；
- 必须有 char budget，不允许无限堆叠。

---

## A3. 新增 session state：rolling summary / 任务锚点状态
建议新增文件：
- `src/plugins/yangyang/core/private_context_session_state.py`

### A3-1. 职责
封装每个私聊 session 的轻量状态：
- 当前任务摘要
- 已确认结论摘要
- 最近一次工具结论摘要
- 待办项
- turn_count
- last_update_ts

### A3-2. 最小接口
建议暴露：
- `get_session_state(session_id)`
- `update_session_state(session_id, event)`
- `build_task_anchor_text(session_id)`
- `flush_session_state()`
- `load_session_state()`

### A3-3. 状态来源
优先从以下事件更新：
- 用户明确下任务
- 工具完成后形成结论
- 模型回复里出现“已确认/待办/下一步”结构
- owner action 明确指向某个施工任务

### A3-4. 第一阶段策略
第一阶段不要搞复杂 NLP 自动摘要，先走**规则式压缩**：
- 当前任务：取最近明确命令
- 已确认：取 owner 明确确认句
- 待办：取 assistant 承诺但未完成项
- 最近工具结论：取“成功/失败/路径/状态”四元组

### A3-5. 持久化策略
第一阶段：
- 默认仅内存
- 可选开启轻量 JSON 落盘

状态文件：
- `data/private_context_session_state.json`

### A3-6. 风险
- 自动摘要写差了会“稳定记错”；
- 所以第一版必须可关、可清空、可只对 owner 私聊启用。

---

## A4. OwnerActionContext：增强摘要，顺手清旧称呼
文件：
- `src/plugins/yangyang/core/owner_action_context_resolver.py`

### A4-1. 先修旧残留
`build_owner_action_context_prompt()` 中当前文案含：
- `漂♂总指令上下文：...`

建议改为：
- `漂♂总指令上下文：...`

这是低风险一致性修复，顺手做掉。

### A4-2. 扩展 summary 价值
当前 `OwnerActionContext.summary` 偏 recent message 概括。
建议扩展为更适合任务锚点输入的结构摘要：
- 场景来源（quote / recent_by_user / recent_current_session）
- 当前动作目标
- 目标对象
- 最近相关消息核心句

### A4-3. 新增输出格式兼容层
给 `build_owner_action_context_prompt()` 加一个保守开关：
- 老格式仍可回退；
- 新格式仅在私聊灰度时启用。

### A4-4. 风险
- 很低；
- 主要注意别把上下文段写太长。

---

## A5. ModelRouter：先补观测，再细分 timeout/fallback
文件：
- `src/plugins/yangyang/core/model_router.py`

### A5-1. 现有基础可复用
已经有：
- tier timeout
- fallback history/stats
- last_call_fallback_* 字段

因此不需要推翻重做，只需加：
1. 调用场景分类；
2. 观测落盘；
3. timeout 读取改为“按场景”；
4. fallback 后软收口标记。

### A5-2. 新增调用场景 bucket
建议定义：
- `first_reply`
- `tool_followup`
- `longform_delivery`
- `tool_progress_push`
- `readonly_diagnostic`

### A5-3. timeout 读取逻辑
新增类似：
- `_resolve_timeout_seconds(tier, call_bucket)`

逻辑：
- 默认仍读 tier timeout；
- 当 `private_context_timeout_strategy_enabled=true` 时：
  - `first_reply` 用 `private_context_timeout_first_reply_seconds`
  - `tool_followup` 用 `private_context_timeout_tool_followup_seconds`
  - `longform_delivery` 用 `private_context_timeout_longform_seconds`

### A5-4. fallback 观测项
增加日志字段：
- requested_profile
- resolved_profile
- fallback_from
- fallback_to
- fallback_reason
- timeout_seconds
- call_bucket
- message_count
- prompt_hash
- tool_call_count
- elapsed_ms

### A5-5. 失败后软收口策略
不是要模型 router 直接生成话术，而是给上层打标：
- `last_call_soft_handoff_recommended = True/False`
- 原因如：`timeout_after_tool_chain`

上层在发现该标记时，优先让回复收口到：
- 已完成什么
- 哪一步卡住
- 下一步建议

避免整轮像没发生过一样重答。

### A5-6. 风险
- 行为改动如果直接开启，可能影响原 fallback 节奏；
- 所以先观测，再灰度启行为。

---

## A6. 工具回灌瘦身：只回灌结论，不回灌大段原文
建议优先检查并改造工具结果回流到模型的公共入口。

优先关联模块：
- `src/plugins/yangyang/core/prompt_builder.py`
- `src/plugins/yangyang/core/owner_toolbox_light.py`
- `src/plugins/yangyang/core/owner_engineering_toolbox.py`
- 如有工具执行后统一整理回复的模块，也一并纳入

### A6-1. 目标
工具回灌只保留：
- 状态：成功/失败
- 核心结果：路径、行数、状态值、命中项
- 异常：error / exception / traceback 摘要
- 下一步所需字段

默认不回灌：
- 完整 stdout
- 完整 stderr
- 超长日志
- 大段目录列表
- 大段文件原文

### A6-2. 建议统一摘要格式
```text
[ToolResultSummary]
- tool: ...
- status: success/fail
- key_result: ...
- error: ...
- next_hint: ...
```

### A6-3. Owner 场景特例
如果 owner 明确要求 raw/debug/stdout/stderr：
- 前台可展示受控调试信息；
- 但给模型二次收口时，仍建议走摘要版，避免污染下一轮。

### A6-4. 风险
- 摘要过头会丢必要细节；
- 所以需要“摘要 + 可选原文缓存引用”，而不是彻底抛弃原始结果。

---

## A7. 测试与验收补点
目录：
- `tests/`

### A7-1. 必补单测
建议新增或扩展测试：
1. **prompt_builder 分层注入测试**
   - 验证硬规则、任务锚点、recent history、tool summary 都能注入；
   - 验证超预算时优先裁 recent，不裁硬规则。

2. **session state 测试**
   - 验证 rolling summary 更新；
   - 验证 turn TTL；
   - 验证持久化开关关闭时不落盘。

3. **model_router timeout bucket 测试**
   - 不同 bucket 取不同 timeout；
   - 开关关闭时仍回落旧逻辑。

4. **fallback observability 测试**
   - 触发 fallback 时日志字段完整；
   - 不泄露敏感配置字段。

5. **owner_action_context_resolver 文案与摘要测试**
   - 确保旧称呼残留被替换；
   - 确保 prompt 文本长度受限。

6. **tool result summary 测试**
   - 长日志输入时只取异常和状态线索；
   - raw 请求关闭时不把大段原文塞回 prompt。

### A7-2. smoke 用例
至少跑以下手工 smoke：
1. 私聊连续 10+ 轮同一工程任务，不丢“当前目标”；
2. 中间插入 3~5 次工具调用，最终收口仍能引用前面确认结论；
3. 模拟一次主模型 timeout，fallback 后仍能说明“已完成到哪一步”；
4. 重启进程后，若启用 state persist，能恢复任务摘要；
5. owner 私聊问模型链、路径、文件位置时，仍遵守受控输出规则。

---

## 5. 灰度步骤

### Phase 0：只加开关和文档
- 改 `runtime_config.py`
- 增补文档
- 不改变线上行为

### Phase 1：只开观测
开启：
- `private_context_observability_enabled=true`
- `private_context_fallback_observability_enabled=true`
- 范围仅 owner 私聊

目的：
- 确认断片主要发生在 recent 被挤掉、工具污染、还是 timeout/fallback 后。

### Phase 2：开任务锚点，但不开持久化
开启：
- `private_context_task_anchor_enabled=true`
- `private_context_rolling_summary_enabled=true`
- `private_context_rolling_summary_persist_enabled=false`

目的：
- 先验证“任务锚点常驻”是否明显降低断片。

### Phase 3：开工具回灌瘦身
开启：
- `private_context_tool_result_summary_enabled=true`

目的：
- 降低多工具后 prompt 被污染。

### Phase 4：开 timeout 分桶策略
开启：
- `private_context_timeout_strategy_enabled=true`

目的：
- 长文与工具收口不再共用同一 timeout 思路。

### Phase 5：必要时开轻量持久化
开启：
- `private_context_rolling_summary_persist_enabled=true`

目的：
- 解决重启后短期失忆。

---

## 6. 回滚点设计

### 可独立回滚项
1. 观测日志开关
2. 任务锚点开关
3. rolling summary 开关
4. 持久化开关
5. 工具回灌摘要开关
6. timeout 分桶开关

### 回滚原则
- 任一阶段出问题，先关对应开关，不必整包回退；
- 只有结构性 bug 才回滚代码。

### 回滚前建议备份
- `src/plugins/yangyang/admin/runtime_config.py`
- `src/plugins/yangyang/core/prompt_builder.py`
- `src/plugins/yangyang/core/model_router.py`
- `src/plugins/yangyang/core/owner_action_context_resolver.py`
- 新增 session state 文件
- 相关测试文件

---

## 7. 实施优先级

### 第一优先级（先切）
1. A1 运行时开关
2. A2 PromptBuilder 分层注入骨架
3. A5 ModelRouter 观测增强
4. A6 工具回灌摘要化

### 第二优先级（再切）
5. A3 session state / rolling summary
6. A4 owner_action_context_resolver 一致性修复
7. A7 测试补齐与 smoke

原因：
- 先把“看得见”和“少污染”做起来，收益最大；
- 再做“长期稳态保存”。

---

## 8. 建议的首轮施工顺序
建议真正动刀时按这个顺序提交：

### Commit 1
- runtime_config 新开关
- 文档更新
- 无行为变化

### Commit 2
- prompt_builder 分层注入框架
- observability 落盘
- 默认关闭

### Commit 3
- model_router timeout bucket / fallback 观测
- 默认只开观测

### Commit 4
- 工具回灌摘要化
- owner 私聊灰度

### Commit 5
- session state + rolling summary
- 先内存后落盘

### Commit 6
- tests + smoke

---

## 9. 完成标准
满足以下条件，视为本轮施工达标：
1. 私聊连续多轮任务中，当前目标不再轻易丢失；
2. 多工具后最终收口仍能引用前序确认结论；
3. timeout/fallback 发生时，有明确观测日志可追；
4. 重启前后（若开启 persist）任务锚点能恢复；
5. 任一子能力都可通过开关独立关闭；
6. 不引入路径/密钥/原始调试信息泄露问题。

---

## 10. 下一步建议
建议下一张单直接进入：
- **“Phase 0 + Phase 1 实施单”**

也就是：
1. 先补 runtime config 开关；
2. 先补 observability；
3. 不改线上主行为；
4. 先拿数据，再切锚点和摘要。

这条路线最稳，改炸概率最低，也最容易让秧秧接手兜底。

---

## 11. v2 留痕补充：三条架构红线

基于最新 review，本单补充以下三条为**强制前提**，后续实现与验收都按这个来，不再各自分叉。

### 11.1 Single Source of Truth
**结论：`private_context_session_state` 为唯一状态源。**

约束如下：
- `private_context_session_state` 负责唯一写入与持久化；
- `task_anchor` 与 `owner_action_context` 只做**派生视图**，不允许各自维护一套并行摘要；
- prompt 注入、观测日志、回滚恢复，都以这一份状态为准；
- 禁止出现“三套摘要并行更新”的实现。

目的：
- 避免状态漂移、摘要打架、更新顺序不一致；
- 防止模型一轮里看到互相矛盾的任务描述。

### 11.2 工具回灌：摘要 + 证据切片白名单
**结论：工具回灌不能只留结论，必须保留少量证据切片。**

允许进入 prompt 的证据切片类型建议如下：
- traceback 尾段；
- exception / error 主句；
- diff 关键 hunks；
- grep / config 命中片段；
- 测试失败断言附近几行；
- systemd / status 输出中的核心异常句。

约束如下：
- 默认仍以摘要为主；
- 白名单证据只允许少量、定向、可控进入 prompt；
- 不允许把整段 stdout / stderr / 大日志原样灌回去；
- 超预算时优先裁大段原文，保留高价值证据切片。

目的：
- 防止“只看结论，不看依据”导致排障误判；
- 保留必要原文线索，但不把 prompt 塞爆。

### 11.3 timeout bucket 显式传入，router 不自行猜测
**结论：timeout bucket 由上层调用方显式传入，`model_router` 只消费，不做业务推断。**

约束如下：
- 上层负责判断本轮属于哪类调用：`first_reply`、`tool_followup`、`longform_delivery` 等；
- `model_router` 不允许根据消息内容、工具痕迹、长度去猜 bucket；
- 路由层只负责：读取 bucket、选择 timeout、记录 fallback 观测；
- 禁止在 router 内部长出一坨业务 `if/else` 猜测逻辑。

目的：
- 保持职责边界清楚；
- 避免路由层逐渐演化成不可维护的条件树；
- 让超时策略可测、可追、可回滚。

### 11.4 施工单执行顺序同步更新
后续落地时，优先级修正为：
1. `private_context_session_state` SSOT；
2. 工具回灌证据切片白名单；
3. timeout bucket 显式传入；
4. 其余分层注入、观测、灰度与测试按原计划推进。

### 11.5 结论
这三条不再作为“可选优化”，而是**结构性约束**：
- 先定骨架，再上功能；
- 先防状态分裂，再谈摘要质量；
- 先防路由膨胀，再谈超时体验。

