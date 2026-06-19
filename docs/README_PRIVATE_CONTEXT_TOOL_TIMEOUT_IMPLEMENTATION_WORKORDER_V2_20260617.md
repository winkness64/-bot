# README_PRIVATE_CONTEXT_TOOL_TIMEOUT_IMPLEMENTATION_WORKORDER_V2_20260617.md

## 1. 文档定位
本文件为 `README_PRIVATE_CONTEXT_TOOL_TIMEOUT_IMPLEMENTATION_WORKORDER_20260617.md` 的 **v2 修订留痕版**。

修订原因：
- 漂♂总确认第二份施工单可开工；
- 秧秧补充三条关键架构建议；
- 当前线上最急迫问题是 **LLM 超时导致回答中断/失忆体感**，以及 **非流式输出导致整轮等待过长**；
- 因此本版在原施工单基础上，增加三条硬约束，并把 **“先改超时 + 流式输出”** 提升为最先开工项。

本版目标：
1. 留痕三条架构红线；
2. 避免后续施工长成三套摘要、router 猜业务、工具回灌只剩空结论；
3. 明确 Phase 0 / Phase 1 的最小开工范围；
4. 保持可灰度、可回滚、可停火。

---

## 2. v2 三条硬约束（必须写进施工前提）

### 2.1 SSOT：`private_context_session_state` 是唯一状态源
**结论：**
- `private_context_session_state` 作为 **single source of truth**；
- `task anchor` 与 `owner action context` 只允许作为 **渲染视图 / 派生视图**；
- 禁止形成三套独立摘要并行写入。

**允许：**
- 一个状态源写入；
- 多个 prompt 视图从该状态源派生；
- 各视图按预算裁剪、格式化，但不回写成独立真相。

**禁止：**
- `task anchor` 自己维护一套长期任务摘要；
- `owner action context` 自己维护另一套结论状态；
- PromptBuilder 内部再偷偷滚一套 rolling summary。

**原因：**
三套摘要并行的后果通常是：
- 更新顺序不一致；
- 已确认结论漂移；
- 某层显示“已完成”，另一层仍显示“待确认”；
- 线上 debug 时无法判断哪层是真相。

**工程要求：**
- 所有任务级状态写入统一经过 `private_context_session_state`；
- `build_task_anchor_text(...)`、`build_owner_action_context_prompt(...)` 只能读，不直接持久化独立摘要；
- 调试日志围绕该状态对象打点。

---

### 2.2 工具回灌必须是“摘要 + 证据切片白名单”双轨
**结论：**
工具回灌不能只保留结论，必须允许少量高价值原文证据进入 prompt。

**保留原因：**
只回灌“结论”会丢掉判断依据，排障场景会发虚，尤其是：
- traceback 尾段；
- exception/message 主体；
- diff 关键块；
- grep/config 命中片段；
- 测试失败断言附近几行；
- systemd 状态中的核心 error/warn 句。

**白名单建议：**
允许进入 prompt 的证据切片类型：
1. `traceback_tail`
2. `exception_message`
3. `diff_hunk_key`
4. `grep_hit_excerpt`
5. `config_hit_excerpt`
6. `assertion_failure_excerpt`
7. `status_error_line`
8. `last_n_error_lines`

**预算约束：**
- 每类最大条数；
- 每条最大字符数；
- 总证据预算上限；
- 超预算时优先保留错误类、断言类、配置命中类片段。

**禁止：**
- 工具回灌只有一句“疑似超时/疑似配置问题”；
- 无上限塞完整 stdout/stderr/log；
- 目录长列表、重复状态输出原样灌回 prompt。

---

### 2.3 timeout bucket 由上层显式传入，`model_router` 只消费
**结论：**
`model_router` 不负责猜“当前是首答/工具后/长文/收口轮”，bucket 必须由上层调用方显式传入。

**职责边界：**
上层调用方负责决定：
- `timeout_bucket`
- `interaction_phase`
- 是否允许 fallback
- 是否允许流式
- 是否允许软收口

`model_router` 只负责：
- 按传入 bucket 取超时参数；
- 执行模型请求；
- 记录 timeout/fallback 结果；
- 返回结构化调用结果。

**禁止：**
- 在 router 中堆业务语义判断；
- router 内部用 if/else 猜“这轮像不像长文”；
- router 顺手决定该不该流式或该不该改写 prompt 结构。

**原因：**
否则 router 会越来越懂业务，最终长成一坨难回滚的逻辑尸山。

---

## 3. 优先级调整：先止血，再重构上下文
原单中上下文与 session state 施工重要，但当前线上最痛点是：
1. 回答超时；
2. 非流式导致用户长时间看不到输出；
3. 超时后整轮收口失败，看起来像断片。

因此 v2 将优先级重排为：

### P0：先解决“会死”
- 拉开 LLM timeout bucket；
- 明确由上层显式传 bucket；
- 为后续流式输出打接口位；
- 保持默认行为可回滚。

### P1：再解决“慢但无感知”
- 接前台流式输出；
- 优先让用户先看到 token 流出；
- 降低“整段生成完才发送”的超时风险。

### P2：最后解决“能活但会漂”
- SSOT session state；
- task anchor 派生；
- 工具回灌摘要 + 证据切片；
- owner action context 去状态化。

一句话：
**先把“会死”改成“会慢但能活”，再把“能活”修到“稳”。**

---

## 4. 最小开工范围（本轮建议直接施工）

## 4.1 Phase 0：LLM timeout bucket 化
### 目标
把统一 timeout 拆成显式 bucket，先缓解超时导致的整轮失败。

### 范围
优先涉及：
- `src/plugins/yangyang/admin/runtime_config.py`
- `src/plugins/yangyang/core/model_router.py`
- 调用 `model_router` 的上层入口（实际发起回复、工具后收口、长文交付的地方）

### 建议新增配置
```python
"llm_timeout_bucket_enabled": False,
"llm_timeout_bucket_default": "normal",
"llm_timeout_seconds_fast": 45,
"llm_timeout_seconds_normal": 90,
"llm_timeout_seconds_tool_followup": 150,
"llm_timeout_seconds_longform": 210,
"llm_timeout_seconds_streaming_first_token": 30,
"llm_timeout_fallback_enabled": True,
"llm_timeout_soft_finish_enabled": True,
```

### bucket 建议枚举
- `fast`：普通短回复
- `normal`：默认轮次
- `tool_followup`：工具后收口
- `longform`：长文交付
- `streaming_first_token`：流式首 token 等待

### 代码要求
- 上层显式传 bucket 给 `model_router`；
- `model_router` 仅消费 bucket，不自己猜；
- 记录本轮 `timeout_bucket`、`timeout_seconds`、`fallback_used`；
- timeout 后允许触发更保守 fallback，但不要直接丢失原轮次上下文标记。

### 验收
- 同样 prompt 下，长文/工具收口不再沿用短回复 timeout；
- 日志里能明确看到每轮 bucket；
- timeout 发生时能判断是配置太紧，还是模型真实卡死。

---

## 4.2 Phase 1：输出改流式
### 目标
降低“整段攒完才发”的等待与超时风险，改善用户体感。

### 范围
先只做 **前台可见的最小流式链路**，不在第一刀里做复杂多路复用。

优先排查/接入位置：
- 回复发送入口；
- 模型调用结果消费入口；
- 若现有 provider 支持流式，则优先走 provider 原生流；
- 若暂不支持完整流，也要先做“占位短消息 + 分段续发”降级方案。

### 分层目标
#### 第一层：真流式优先
- 若底层模型 SDK / OpenAI-compatible provider 支持 streaming；
- 则先接首 token 到达即开始向前台推送；
- 前台按增量块刷新。

#### 第二层：降级伪流式
若某链路暂时不能真流式：
- 先发一条短进度消息；
- 模型完成后按分段输出，而不是整段一次性砸出；
- 工具型轮次先发“在查 / 处理中”，再补结论。

### 关键指标
- `time_to_first_token`
- `time_to_first_visible_output`
- `full_response_time`
- `stream_interrupted`
- `stream_fallback_to_nonstream`

### 验收
- 用户在长文轮次能更早看到输出；
- 即便最终总时长没大降，体感也不再像超时假死；
- 流式失败时可平滑降级，不整轮报错。

---

## 5. 原施工单的修订点

### 5.1 对 A2 / A3 / A4 的修订
原施工单中：
- A2 = PromptBuilder 分层注入
- A3 = 新增 session state
- A4 = OwnerActionContext 增强摘要

v2 修订为：
- A3 提升为核心：`private_context_session_state` 为唯一写入状态源；
- A2 的 task anchor 只能从 A3 派生；
- A4 的 owner action context 只能从 A3 + recent messages 派生，不得自存长期摘要。

### 5.2 对 A5 的修订
原 A5 中“按轮次类型区分 timeout/fallback 策略与观测”保留，
但补充硬要求：
- 轮次类型不由 `model_router` 自己判断；
- bucket 必须上层显式传入；
- router 只做参数消费与观测记录。

### 5.3 对 A6 的修订
原 A6“工具回灌瘦身入口”保留，
但补充硬要求：
- 不是“只留结论”；
- 必须支持“摘要 + 证据切片白名单”；
- 证据片段预算单独配置，不与普通 recent history 混用。

---

## 6. 建议新增配置（v2 补充）
在原施工单配置基础上，补充：

```python
"private_context_session_state_enabled": False,
"private_context_session_state_persist_enabled": False,
"private_context_session_state_path": "data/private_context_session_state.json",

"private_context_tool_evidence_enabled": False,
"private_context_tool_evidence_char_budget": 600,
"private_context_tool_evidence_max_items": 6,
"private_context_tool_evidence_types": [
    "traceback_tail",
    "exception_message",
    "diff_hunk_key",
    "grep_hit_excerpt",
    "config_hit_excerpt",
    "assertion_failure_excerpt",
    "status_error_line",
    "last_n_error_lines",
],

"llm_timeout_bucket_enabled": False,
"llm_timeout_bucket_default": "normal",
"llm_timeout_seconds_fast": 45,
"llm_timeout_seconds_normal": 90,
"llm_timeout_seconds_tool_followup": 150,
"llm_timeout_seconds_longform": 210,
"llm_timeout_seconds_streaming_first_token": 30,

"llm_streaming_enabled": False,
"llm_streaming_owner_only_gray_enabled": True,
"llm_streaming_progressive_flush_enabled": False,
"llm_streaming_fake_fallback_enabled": True,
```

---

## 7. 开工顺序（v2）

### Step 1
只改配置项与枚举定义：
- 新增 timeout bucket 配置；
- 新增 streaming 开关；
- 不改线上默认行为。

### Step 2
改 `model_router` 入参：
- 接收 `timeout_bucket`；
- 接收是否允许 streaming；
- 内部只消费，不推理业务语义。

### Step 3
改上层调用方：
- 普通短回复传 `fast` / `normal`；
- 工具后收口传 `tool_followup`；
- 长文交付传 `longform`；
- 流式链路优先给长文和工具收口。

### Step 4
接最小流式前台输出：
- 先 owner 私聊灰度；
- 失败自动回退非流式或伪流式；
- 观测首 token 时间。

### Step 5
再进 SSOT 和工具证据回灌改造。

---

## 8. 风险与回滚

### 风险 1：timeout 拉大后吞吐下降
处理：
- 按 bucket 精细化，不是全局一刀切；
- owner-only 灰度。

### 风险 2：流式链路引入前台发送碎片
处理：
- 先在 owner 私聊灰度；
- 先做较大 chunk flush，不要 token 级过碎发送。

### 风险 3：真流式链路不稳定
处理：
- 允许自动降级为伪流式或非流式；
- 前台至少先看到进度消息。

### 回滚原则
- 所有新行为默认开关关闭；
- 回滚优先关开关，不先删代码；
- 真炸了再回退相关模块备份。

---

## 9. 本版结论
v2 的核心不是多写几段文案，而是钉死三条红线：
1. **SSOT 只能有一个：`private_context_session_state`**
2. **工具回灌必须保留少量证据切片，不许只剩空结论**
3. **timeout bucket 必须上层显式传入，router 只消费**

并且当前最先该动的，不是摘要花活，而是：
- **先把 timeout bucket 化**
- **再把输出改成流式**

这两刀先落，能最快缓解“超时像断片”的狗屎问题。
