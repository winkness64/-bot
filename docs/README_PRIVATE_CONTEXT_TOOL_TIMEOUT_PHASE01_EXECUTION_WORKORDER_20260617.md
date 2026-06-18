# README_PRIVATE_CONTEXT_TOOL_TIMEOUT_PHASE01_EXECUTION_WORKORDER_20260617.md

## 1. 文档定位
本文件为 **Phase 0 + Phase 1 可直接开工施工单**。

目标不是再讲原则，而是把前两份方案和 v2 红线，落成一份能直接照着改的工程执行单。

适用前提：
- 当前最急问题是 **LLM 超时导致回复中断/收口失败**；
- 同时存在 **非流式输出导致首字迟迟不可见**；
- 本轮先止血，不在第一刀里同时重构整套记忆/上下文状态。

本单遵循三条已确认红线：
1. `private_context_session_state` 是唯一状态源（本轮只留接口位，不在 P0/P1 完整实施）；
2. 工具回灌最终要做“摘要 + 证据切片白名单”（本轮先留观测点，不做大改）；
3. `timeout bucket` 由上层显式传入，`model_router` 只消费不猜。

---

## 2. 本轮目标

### 2.1 Phase 0：先止血
把统一 timeout 改成 **显式 bucket 化**，避免：
- 短回复 timeout 套到长文；
- 工具后收口还在吃短时限；
- fallback 太早触发，导致误判主模型不稳定；
- 超时后没有足够日志判断是配置太紧，还是 provider 真卡死。

### 2.2 Phase 1：先把“看起来死了”改成“至少先出字”
输出链路优先补 **最小流式/伪流式可见能力**，降低：
- 用户长时间看不到任何输出；
- 整段攒完才发送，结果死在最后一步；
- 工具型轮次明明在查，前台却像挂机。

---

## 3. 真实代码落点（按当前仓库骨架）

已核对当前项目中与本轮最相关的真实文件：

### 3.1 配置层
- `src/plugins/yangyang/admin/runtime_config.py`
- `src/plugins/yangyang/data/runtime_config.json`

### 3.2 路由与提示层
- `src/plugins/yangyang/core/model_router.py`
- `src/plugins/yangyang/core/prompt_builder.py`
- `src/plugins/yangyang/core/owner_action_context_resolver.py`
- `src/plugins/yangyang/core/owner_action_reply_draft.py`
- `src/plugins/yangyang/__init__.py`

### 3.3 输出层
- `src/plugins/yangyang/output/sender.py`
- `src/plugins/yangyang/output/sender_adapter.py`
- `src/plugins/yangyang/output/sender_adapter_factory.py`

### 3.4 Provider 层（按需）
- `src/plugins/yangyang/core/model/provider_openai_compat.py`
- `src/plugins/yangyang/core/model/provider_deepseek.py`
- `src/plugins/yangyang/core/model/provider_base.py`

说明：
- 本轮 **优先改配置层、router 层、输出层**；
- provider 层只在确认为支持 streaming 时补透传；
- `prompt_builder / owner_action_context_resolver` 本轮只做 bucket 透传与日志埋点，不做结构性重构。

---

## 4. Phase 0 施工单：LLM timeout bucket 化

## 4.1 目标定义
把“一个 provider 一个 timeout”的现状，升级为：
- provider 仍保留基础 timeout；
- 但每次调用由上层传入 `timeout_bucket`；
- `model_router` 根据 bucket 决定本次超时参数；
- 所有关键日志带上本次 bucket 和最终 timeout 秒数。

---

## 4.2 配置项新增

### 文件
- `src/plugins/yangyang/admin/runtime_config.py`
- `src/plugins/yangyang/data/runtime_config.json`（按需补默认值）

### 建议新增默认配置
```python
"llm_timeout_bucket_enabled": False,
"llm_timeout_bucket_default": "normal",
"llm_timeout_bucket_allow_override_provider_timeout": True,
"llm_timeout_seconds_fast": 45,
"llm_timeout_seconds_normal": 90,
"llm_timeout_seconds_tool_followup": 150,
"llm_timeout_seconds_longform": 210,
"llm_timeout_seconds_streaming_first_token": 30,
"llm_timeout_seconds_streaming_total": 240,
"llm_timeout_fallback_enabled": True,
"llm_timeout_soft_finish_enabled": True,
"llm_timeout_observability_enabled": True,
"llm_streaming_enabled": False,
"llm_streaming_private_enabled": True,
"llm_streaming_group_enabled": False,
"llm_streaming_progress_notice_enabled": True,
"llm_streaming_progress_notice_text": "在查，等我切两刀。",
"llm_streaming_fake_stream_chunk_chars": 120,
"llm_streaming_fake_stream_interval_ms": 350,
```

### bucket 建议枚举
- `fast`：极短答复 / 普通一轮
- `normal`：默认轮次
- `tool_followup`：工具执行后收口
- `longform`：长文、施工单、总结交付
- `streaming_first_token`：仅用于真流式首 token 等待
- `streaming_total`：流式整轮总时限

说明：
- 第一刀里不必所有 bucket 都完全用上；
- 但配置先一次补齐，避免第二刀再改 schema。

---

## 4.3 `model_router.py` 改动要求

### 当前现状
`ModelRouter` 目前已有：
- `_tier_timeout(tier)`：按 provider/profile 取 timeout；
- fallback 统计与状态记录；
- 多 profile 路由能力。

问题是：
- timeout 仍偏“按模型静态配置”；
- router 层没有显式消费 `timeout_bucket` 的接口；
- 上层无法稳定表达“这轮就是工具后收口 / 长文交付”。

### 要做的改动

#### A. 新增 bucket 解析函数
建议在 `ModelRouter` 内新增：
```python
def _resolve_timeout_bucket(self, timeout_bucket: str | None) -> str: ...
def _resolve_timeout_seconds(self, tier: str, timeout_bucket: str | None) -> float: ...
```

职责：
- `timeout_bucket` 为空时走 `llm_timeout_bucket_default`；
- 若 `llm_timeout_bucket_enabled=False`，则回退 `_tier_timeout(tier)`；
- 若启用 bucket，则按 bucket 秒数取值；
- 是否覆盖 provider timeout，受 `llm_timeout_bucket_allow_override_provider_timeout` 控制。

#### B. 路由主调用签名补参数
给主调用入口新增可选参数：
```python
timeout_bucket: str | None = None,
allow_streaming: bool | None = None,
interaction_phase: str | None = None,
```

要求：
- `timeout_bucket` 是上层业务显式传入；
- `interaction_phase` 只做日志标签，不在 router 内部触发业务判断；
- `allow_streaming` 只决定是否向 provider 传 streaming 能力，不在 router 内部猜测场景。

#### C. 日志与状态补充
至少补这些字段：
- `last_call_timeout_bucket`
- `last_call_timeout_seconds`
- `last_call_interaction_phase`
- `last_call_streaming_enabled`

若已有 request 级审计/usage 事件，也把下列字段塞进去：
- `timeout_bucket`
- `timeout_seconds`
- `interaction_phase`
- `streaming`
- `fallback_used`
- `resolved_profile`

#### D. timeout 异常分型
超时时日志至少区分：
- `provider_timeout`
- `first_token_timeout`
- `streaming_total_timeout`
- `unknown_timeout`

先不追求 provider 统一异常体系，第一刀只要**日志可读**。

---

## 4.4 上层调用方改动要求

### 关键红线
**bucket 由上层传，不准 router 猜。**

### 建议分配规则
按当前业务链，先做最小映射：

#### 普通私聊/普通群聊
传：
```python
timeout_bucket="normal"
interaction_phase="direct_reply"
allow_streaming=False  # 第一刀可先关
```

#### 工具执行后的最终收口
传：
```python
timeout_bucket="tool_followup"
interaction_phase="tool_followup"
allow_streaming=False 或 True（视链路准备度）
```

#### 长文交付 / 施工单 / 结构化总结
传：
```python
timeout_bucket="longform"
interaction_phase="longform_delivery"
allow_streaming=True
```

#### 真流式时首 token 等待
这里不要从上层直接把整个轮次都标成 `streaming_first_token`。
正确做法：
- 上层仍传业务 bucket（如 `longform`）；
- provider/route 内部再拆“首 token 等待超时”和“总超时”；
- 这样不会把 bucket 语义搞乱。

### 优先排查入口
建议先 grep / 手改这些调用点：
- `src/plugins/yangyang/__init__.py` 中直接或间接调用 router 的入口
- `owner_action_reply_draft.py`
- 工具结果收口相关逻辑
- 长文报告/交付相关逻辑

---

## 4.5 Phase 0 具体步骤

### Step P0-1：加配置，不改行为
- 在 `runtime_config.py` 增加上述配置默认值；
- `runtime_config.json` 如有固定运行态模板，同步补齐；
- 默认 `llm_timeout_bucket_enabled=False`；
- 验证旧逻辑不变。

### Step P0-2：给 `ModelRouter` 加 bucket 参数与日志
- 补 `timeout_bucket / interaction_phase / allow_streaming` 参数；
- 先接参数，但 `llm_timeout_bucket_enabled=False` 时仍走旧 timeout；
- 补日志字段。

### Step P0-3：上层调用透传 bucket
- 至少接通三种：`normal / tool_followup / longform`；
- 第一轮不追求所有分支完整覆盖；
- 未覆盖分支统一显式传 `normal`，不要留“默认猜”。

### Step P0-4：打开 bucket 开关灰度
建议灰度顺序：
1. 私聊 owner 单通道先开；
2. 仅长文 / 工具收口先开；
3. 观察 1~2 小时日志；
4. 再扩大到普通私聊；
5. 最后再考虑群聊。

---

## 4.6 Phase 0 验收标准

### 必过
1. 同一 active profile 下：
   - 普通短答使用 `normal`；
   - 工具后收口使用 `tool_followup`；
   - 长文交付使用 `longform`。
2. 日志能直接看到：
   - 本轮 bucket；
   - 本轮 timeout 秒数；
   - 是否 fallback；
   - 最终 resolved profile。
3. `llm_timeout_bucket_enabled=False` 时，行为与旧版本基本一致。

### 观察项
- timeout 频率是否下降；
- fallback 是否更少误触发；
- 长文失败是否明显减少；
- 工具轮结束后“断片”是否减少。

---

## 5. Phase 1 施工单：前台最小流式 / 伪流式可见输出

## 5.1 目标定义
这轮不追求完美 token-by-token 架构，而是追求：
- **先让用户尽快看到内容开始出来**；
- 即便 provider 暂不支持真流式，也要有“进度提示 + 分段续发”降级；
- 输出层改动尽量收束在 `sender.py / sender_adapter.py` 附近。

---

## 5.2 当前输出层现状（已核对）

### `src/plugins/yangyang/output/sender.py`
当前能力：
- `send(...)` 一次性发送清洗后的完整文本；
- 私聊长文支持合并转发或 chunked fallback；
- 但没有“先发进度，再补正文”的流式/伪流式接口。

### `src/plugins/yangyang/output/sender_adapter.py`
当前能力：
- `send_current_session(...)` 是单次内容发送；
- 支持短文本直发、长文本 forward；
- 但没有统一的增量更新/进度推送抽象。

结论：
- 第一刀不要试图在适配器层做“消息编辑”；
- OneBot v11 本来也不适合指望稳定编辑消息；
- 直接做 **进度提示 + 分段发送 / 真流式分块发送** 更现实。

---

## 5.3 Phase 1 两层方案

### 方案 A：真流式优先（provider 支持时）
适用条件：
- `provider_openai_compat.py` 或其他 provider 已支持 stream=True 类接口；
- 能在异步迭代中拿到 token / delta。

要求：
1. `model_router` 增加 streaming 调用分支；
2. provider 返回 async iterator 或 chunk 回调；
3. 输出层累计到一定字符数/句号边界后发送一块；
4. 首块尽快发，后续按预算续发；
5. 最终仍要有完整收口文本用于入库和审计。

### 方案 B：伪流式降级（第一刀必须有）
即使 provider 还没接好真流式，也先做：
1. 发送一条短进度提示；
2. 模型完成后把正文按块发送；
3. 工具型轮次优先发“在查/处理中”；
4. 长文轮次优先按自然段或句群分块，而不是一次性 2k+ 文本砸出。

**建议：第一刀先把 B 做稳，再补 A。**

---

## 5.4 `sender.py` 改动要求

### 建议新增接口
```python
async def send_progress_notice(self, msg: Message, text: str) -> None: ...
async def send_chunked_visible(self, msg: Message, decision: Decision, text: str, actual_tier: str = "") -> None: ...
```

#### A. `send_progress_notice(...)`
职责：
- 私聊/群聊发一条很短的“正在处理”提示；
- 只在 `llm_streaming_progress_notice_enabled=True` 时启用；
- 避免重复刷多条，必要时同轮只允许一次。

建议默认文本：
- 私聊：`在查，等我切两刀。`
- 工具后：`在查日志，马上给你结论。`

#### B. `send_chunked_visible(...)`
职责：
- 把最终文本按 100~300 字自然切块发送；
- 私聊优先按段落/句群；
- 群聊仍保守，不建议默认打开。

切块规则建议：
1. 先按段落切；
2. 再按句号边界切；
3. 最后才按硬长度切；
4. 每块尽量可独立阅读，不要从词中间截断。

### 注意
- `send(...)` 旧接口保留；
- 新逻辑不要直接替换所有发送路径；
- 先只让长文交付和工具后收口走新接口。

---

## 5.5 `sender_adapter.py` 改动要求

这层第一刀只做轻改，不搞复杂协议。

### 建议新增轻量接口
```python
async def send_current_session_progress(self, message: Any, content: str) -> SendResult: ...
async def send_current_session_chunks(self, message: Any, chunks: list[str]) -> list[SendResult]: ...
```

如果不想改 Protocol 太多，也可以：
- 先在具体 adapter 类里实现；
- 上层判定存在该方法就调用；
- 没有就回退现有 `send_current_session(...)`。

### 要求
- progress 消息和 chunk 正文都沿用现有 current session 发法；
- 不要求消息编辑；
- 不要求撤回；
- 不要求 forward 与流式强绑定。

这样第一刀风险最小。

---

## 5.6 provider / router 流式接口建议

### 若 provider 已支持 stream
建议 `model_router` 提供并行但独立的入口，例如：
```python
async def generate_text(...): ...
async def stream_text(...): ...
```

不要把所有逻辑硬塞一个函数里通过 `if stream` 分叉到满地都是。

### `stream_text(...)` 最低要求
返回结构至少能表达：
- `delta_text`
- `is_final`
- `request_id`
- `resolved_profile`
- `error_type`（如有）

### 若 provider 暂不支持真流
则本轮只完成：
- bucket 化 timeout；
- 前台 progress notice；
- 长文 chunk visible。

这已经能先显著改善“超时体感”。

---

## 5.7 Phase 1 具体步骤

### Step P1-1：先做 progress notice
- 在 owner 私聊 / 工具收口场景先启用；
- 同轮仅发一次；
- 默认可开关控制。

### Step P1-2：做 chunk visible 输出
- 给长文交付和工具后收口接 `send_chunked_visible(...)`；
- 分块粒度先保守；
- 不要一上来模拟逐 token 刷屏。

### Step P1-3：视 provider 情况补真流式
- 如果 `provider_openai_compat.py` 好接，就补；
- 不好接，本轮先不强推；
- 以不炸主链为第一优先。

### Step P1-4：灰度打开
建议顺序：
1. owner 私聊长文交付；
2. owner 私聊工具后收口；
3. owner 私聊普通长回复；
4. 非 owner 私聊；
5. 群聊默认先不开真流式。

---

## 5.8 Phase 1 验收标准

### 必过
1. 长文场景下，前台能更早看到可见输出；
2. 工具型场景下，前台至少先看到“在查/处理中”；
3. 发送失败时仍能回退到旧单次发送；
4. 不影响当前私聊长文合并转发稳定性。

### 指标建议
- `time_to_first_visible_output`
- `time_to_full_delivery`
- `streaming_mode`（real / fake / disabled）
- `chunk_count`
- `chunk_total_chars`

---

## 6. 本轮不做什么

为了不把第一刀做成暗黑♂幻想，本轮明确 **不做**：

1. 不在 P0/P1 完整重构 `private_context_session_state`；
2. 不在本轮实现全量证据切片白名单入 prompt；
3. 不做 router 内复杂业务猜测；
4. 不在群聊默认开启高频流式刷屏；
5. 不要求 provider 层一次性统一成完美流式抽象；
6. 不动冷备、记忆入库、长期记忆主流程。

---

## 7. 风险点与回滚

## 7.1 风险点
### 风险 A：bucket 接口加了，但上层漏传
后果：
- 又回到隐式默认；
- 日志看起来能跑，实际上语义不清。

**处理：**
- 未显式传 bucket 的关键入口，日志打 warning；
- 第一刀允许回落 `normal`，但要留痕。

### 风险 B：progress notice 过多，像刷屏
**处理：**
- 同轮只允许一次；
- 默认只在 owner 私聊和工具收口开。

### 风险 C：chunk visible 破坏阅读连续性
**处理：**
- 先按自然段 / 句群切；
- 每块字数别太碎；
- 群聊默认不开。

### 风险 D：真流式 provider 接不稳
**处理：**
- 立即回退到伪流式；
- 不让真流式成为主链硬依赖。

---

## 7.2 回滚策略

### 软回滚
把这些开关关掉即可：
```python
llm_timeout_bucket_enabled = False
llm_streaming_enabled = False
llm_streaming_progress_notice_enabled = False
```

### 半回滚
- 保留 router 新签名；
- 但上层统一传 `normal`；
- 输出层统一回到旧 `send(...)`。

### 硬回滚
- 回退 `runtime_config.py`
- 回退 `model_router.py`
- 回退 `sender.py`
- 回退 `sender_adapter.py`

本轮最好每个文件改前都留一个 `.bak_<tag>_<timestamp>`。

---

## 8. 建议提交顺序

建议拆成 4 个小提交，不要一把梭：

1. **commit-1：配置与日志接口位**
   - `runtime_config.py`
   - `model_router.py`

2. **commit-2：上层 timeout bucket 透传**
   - `__init__.py`
   - `owner_action_reply_draft.py`
   - 其他 direct router 调用点

3. **commit-3：progress notice + chunk visible**
   - `sender.py`
   - `sender_adapter.py`

4. **commit-4：provider streaming（如果真要做）**
   - `provider_openai_compat.py`
   - `provider_base.py`
   - `model_router.py`

这样炸了也容易切回。

---

## 9. 最小 smoke 清单

### Smoke-1：普通短答
- bucket=`normal`
- streaming=off
- 结果应与旧行为基本一致

### Smoke-2：工具后收口
- bucket=`tool_followup`
- 前台先看到进度提示
- 后续正常给结论

### Smoke-3：长文交付
- bucket=`longform`
- timeout 明显高于普通短答
- 输出可分块或更早可见

### Smoke-4：关闭开关回退
- 关闭 bucket / streaming 开关
- 主链仍能正常回复

### Smoke-5：fallback 观察
- 人工制造一次 timeout
- 确认日志中有：bucket、timeout_seconds、fallback_used、resolved_profile

---

## 10. 最终结论
这轮建议的最小可施工路径很明确：

### 先做
1. `runtime_config.py` 加 timeout / streaming 开关；
2. `model_router.py` 接 `timeout_bucket` 显式透传；
3. 上层把 `normal / tool_followup / longform` 三种 bucket 传起来；
4. `sender.py` 先补 progress notice 和 chunk visible。

### 后做
5. provider 真流式；
6. SSOT session state；
7. 工具回灌证据切片白名单。

一句话：
**先把“超时像死机”切成“慢但能见字”，再往后收拾状态源和回灌质量。**

done。♂爽。
