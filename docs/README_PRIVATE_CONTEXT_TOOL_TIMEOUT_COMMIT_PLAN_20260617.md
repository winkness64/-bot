# README_PRIVATE_CONTEXT_TOOL_TIMEOUT_COMMIT_PLAN_20260617.md

## 1. 文档定位
本文件为 **第四张：按 commit 拆分的实际改动清单**。

用途不是再讲原则，而是把前面三份留痕继续往前推一刀，明确：
- 每个 commit 动哪些真实文件；
- 每个文件先改哪块；
- 哪些地方可以先 stub；
- 哪些地方必须一次改通；
- 怎么做最小 smoke，避免一刀把线上砍翻。

本单基于当前仓库已确认的真实文件位置编写，非空气路径。

---

## 2. 已确认的真实落点

### 2.1 文档留痕
- `/mnt/warehouse/opt_moved/yangyang_nonebot/docs/README_PRIVATE_CONTEXT_TOOL_TIMEOUT_IMPLEMENTATION_WORKORDER_V2_20260617.md`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/docs/README_PRIVATE_CONTEXT_TOOL_TIMEOUT_PHASE01_EXECUTION_WORKORDER_20260617.md`

### 2.2 真实代码文件
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/admin/runtime_config.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/data/runtime_config.json`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/core/model_router.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/__init__.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/core/owner_engineering_toolbox.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/core/owner_toolbox/native_loop.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/output/sender.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/output/sender_adapter.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/output/sender_adapter_factory.py`

### 2.3 已确认的调用链命中点
已确认存在这些真实调用入口：
- `src/plugins/yangyang/__init__.py` 中持有 `ModelRouter`，并存在 `router.call_with_tool_loop(...)`
- `src/plugins/yangyang/core/owner_toolbox/native_loop.py` 中存在：
  - `model_router.call(...)`
  - `model_router.call_with_tool_loop(...)`
- `src/plugins/yangyang/core/owner_engineering_toolbox.py` 中存在：
  - `model_router.call(...)` 用于解析 / 结果格式化类调用
- `src/plugins/yangyang/core/model_router.py` 中存在：
  - `async def call_with_tool_loop(...)`
  - `call()` 与 `call_with_tool_loop()` 返回值约定

结论：
**第四张可以直接按现有骨架施工，不需要再补“先探路文档”。**

---

## 3. 施工总原则

### 3.1 先稳接口，再开功能
顺序必须是：
1. 先立配置；
2. 再改 router 签名与观测；
3. 再改上层入口显式传 bucket；
4. 最后开最小流式 / 伪流式。

### 3.2 第一刀不追求“一步真流式全链打通”
第一刀目标是：
- 超时别再乱套；
- 前台至少先有可见输出；
- 日志里能看出哪轮、哪 bucket、哪种 timeout。

### 3.3 红线保持不变
- `private_context_session_state` 最终是唯一状态源；
- 工具回灌最终要做“摘要 + 证据切片白名单”；
- `timeout_bucket` 只能上层决定，router 不准猜业务。

---

## 4. Commit 计划总览

| Commit | 目标 | 风险级别 | 是否必须一次改通 |
|---|---|---:|---:|
| Commit 1 | 配置 schema 补齐，功能默认关闭 | 低 | 是 |
| Commit 2 | `model_router` 支持 `timeout_bucket / interaction_phase / allow_streaming` + 观测字段 | 中 | 是 |
| Commit 3 | 上层入口显式传 bucket，完成最小场景映射 | 中 | 是 |
| Commit 4 | 发送层增加进度提示与伪流式开关 | 中 | 否，可先 stub |
| Commit 5 | smoke / 灰度 / 回滚开关确认 | 低 | 是 |

---

## 5. Commit 1：补配置 schema，不开功能

### 5.1 目标
把 timeout bucket 和 streaming 开关先做成正式 runtime config 字段，但默认不启用功能，确保后续每个 commit 都不再反复改 schema。

### 5.2 真实文件
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/admin/runtime_config.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/data/runtime_config.json`

### 5.3 本 commit 要做的事

#### A. 在 `runtime_config.py` 增加默认键
建议补：
```python
llm_timeout_bucket_enabled = False
llm_timeout_bucket_default = "normal"
llm_timeout_bucket_allow_override_provider_timeout = True
llm_timeout_seconds_fast = 45
llm_timeout_seconds_normal = 90
llm_timeout_seconds_tool_followup = 150
llm_timeout_seconds_longform = 210
llm_timeout_seconds_streaming_first_token = 30
llm_timeout_seconds_streaming_total = 240
llm_timeout_fallback_enabled = True
llm_timeout_soft_finish_enabled = True
llm_timeout_observability_enabled = True
llm_streaming_enabled = False
llm_streaming_private_enabled = True
llm_streaming_group_enabled = False
llm_streaming_progress_notice_enabled = True
llm_streaming_progress_notice_text = "在查，等我切两刀。"
llm_streaming_fake_stream_chunk_chars = 120
llm_streaming_fake_stream_interval_ms = 350
```

#### B. 在 `runtime_config.json` 补默认值
要求：
- 默认值与 `runtime_config.py` 一致；
- 默认仍保持当前行为：bucket 不启用、streaming 不启用；
- 进度通知开关可以先留 `true`，但发送层未接入前不会生效。

### 5.4 可以先 stub 的部分
- `streaming_first_token / streaming_total` 这两个 bucket 可以先只入 schema，不要求本 commit 用起来；
- `llm_timeout_soft_finish_enabled` 先留键位，不要求马上实现完整软收口。

### 5.5 必须一次改通的部分
- `runtime_config.py` 与 `runtime_config.json` 默认键必须一致；
- 读取这些键时不能抛异常；
- 不启用新开关时，现有行为必须不变。

### 5.6 验收
- 项目能正常启动；
- 读取新配置键不报错；
- 未开启开关时，现有回复流程无行为变化。

---

## 6. Commit 2：改 `model_router.py`，吃显式 bucket

### 6.1 目标
把 router 从“按 tier 静态 timeout”升级为“支持上层显式 timeout bucket”，并补齐日志观测字段。

### 6.2 真实文件
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/core/model_router.py`

### 6.3 当前已确认现状
已确认：
- `ModelRouter` 有 `_tier_timeout(tier)`；
- `ModelRouter` 有 fallback 记录字段；
- `ModelRouter` 有 `call()` 与 `call_with_tool_loop()` 两条主调用链；
- 当前还没有已确认的 `timeout_bucket / interaction_phase / allow_streaming` 正式参数面。

### 6.4 本 commit 要做的事

#### A. 在 `__init__` 中补观测字段
建议新增：
```python
self.last_call_timeout_bucket = ""
self.last_call_timeout_seconds = 0.0
self.last_call_interaction_phase = ""
self.last_call_streaming_enabled = False
self.last_call_timeout_kind = ""
```

#### B. 新增内部解析函数
建议新增：
```python
def _resolve_timeout_bucket(self, timeout_bucket: str | None) -> str: ...
def _resolve_timeout_seconds(self, tier: str, timeout_bucket: str | None) -> float: ...
def _streaming_allowed(self, allow_streaming: bool | None, channel_scope: str | None = None) -> bool: ...
```

规则建议：
- `timeout_bucket is None` → 走 `llm_timeout_bucket_default`；
- `llm_timeout_bucket_enabled=False` → 回退 `_tier_timeout(tier)`；
- 若 bucket 开启，则按 bucket 秒数取值；
- 是否覆盖 provider timeout，受 `llm_timeout_bucket_allow_override_provider_timeout` 控制；
- `allow_streaming` 若为 `None`，以配置开关为准，但不自行推断业务阶段。

#### C. 改 `call()` 签名
建议补：
```python
timeout_bucket: str | None = None,
interaction_phase: str | None = None,
allow_streaming: bool | None = None,
```

要求：
- 兼容旧调用方，不传也能跑；
- 参数只作为消费信号，不触发 router 内部业务脑补；
- 记录到 `last_call_*` 观测字段里。

#### D. 改 `call_with_tool_loop()` 签名
同样补：
```python
timeout_bucket: str | None = None,
interaction_phase: str | None = None,
allow_streaming: bool | None = None,
```

要求：
- 工具环的收口轮必须能把 bucket 一路带下去；
- trace 里最好补入 `timeout_bucket / timeout_seconds`，方便事后对账。

#### E. timeout 异常分型
建议最小补：
- `provider_timeout`
- `first_token_timeout`
- `streaming_total_timeout`
- `unknown_timeout`

第一刀不追求 provider 全统一，只要求日志里能区分类型。

### 6.5 可以先 stub 的部分
- 真正 provider 原生 streaming 透传可以先只留参数位；
- `first_token_timeout` 可先在未接真流式时统一落到 `provider_timeout` 或 `unknown_timeout`；
- token usage 事件里若暂时没位置加，也至少保证 logger 里有字段。

### 6.6 必须一次改通的部分
- `call()` 和 `call_with_tool_loop()` 的新参数必须兼容旧调用；
- `timeout_bucket` 生效时，最终 timeout 秒数必须可观测；
- timeout 发生时，日志里必须能看到 bucket / phase / resolved profile / fallback_used；
- 不传 bucket 时，旧逻辑仍能跑。

### 6.7 验收
- 普通调用不报签名错误；
- 新增参数传入后，router 日志能看到 bucket；
- 同 tier 在不同 bucket 下能解析出不同 timeout；
- 未开 bucket 开关时，仍回退旧 `_tier_timeout()` 行为。

---

## 7. Commit 3：改上层入口，显式传 bucket

### 7.1 目标
把“这是普通回复 / 工具后收口 / 长文交付”的判断留在上层入口，不让 router 猜。

### 7.2 真实文件
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/__init__.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/core/owner_toolbox/native_loop.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/core/owner_engineering_toolbox.py`

### 7.3 已确认的真实命中点
- `__init__.py` 存在 `router.call_with_tool_loop(...)`
- `owner_toolbox/native_loop.py` 存在：
  - `model_router.call(...)`
  - `model_router.call_with_tool_loop(...)`
- `owner_engineering_toolbox.py` 存在：
  - `model_router.call(...)` 用于 intent parser / result formatter 类调用

### 7.4 本 commit 要做的事

#### A. `__init__.py`
先梳理三类场景：
1. 普通回复
2. owner 工具相关回复
3. 明确长文交付 / 结构化总结

建议最小映射：
```python
# 普通回复
timeout_bucket="normal"
interaction_phase="direct_reply"
allow_streaming=False

# owner 工具后收口
timeout_bucket="tool_followup"
interaction_phase="tool_followup"
allow_streaming=False

# 长文交付
timeout_bucket="longform"
interaction_phase="longform_delivery"
allow_streaming=True  # 若发送层未就绪，可先传 False
```

#### B. `owner_toolbox/native_loop.py`
这里至少有两种 LLM 调用：
1. 计划/意图解析；
2. 工具后最终收口。

建议：
- 计划解析 → `timeout_bucket="normal"` 或 `fast`；
- 工具后收口 → `timeout_bucket="tool_followup"`；
- 若有长总结/审计说明 → `timeout_bucket="longform"`。

#### C. `owner_engineering_toolbox.py`
已确认这里有：
- `_build_intent_prompt(...)` 对应的 `model_router.call(...)`
- `_build_result_formatter_prompt(...)` 对应的 `model_router.call(...)`

建议：
- 意图解析 → `fast` 或 `normal`
- 结果格式化 / 汇总结论 → `tool_followup` 或 `longform`

### 7.5 可以先 stub 的部分
- `allow_streaming=True` 可以先不真正打到 provider，只要参数链通了就行；
- phase 枚举可以先少量，别一上来造十几种。

### 7.6 必须一次改通的部分
- 至少主要入口全部显式传 bucket；
- 工具后收口不能再吃普通短超时；
- 长文交付入口必须有独立 bucket；
- 不能把 bucket 判断再偷偷塞回 router。

### 7.7 验收
- 普通聊天日志显示 `direct_reply / normal`；
- 工具后收口显示 `tool_followup / tool_followup`；
- 长文交付显示 `longform / longform_delivery`；
- 同类调用链参数可对齐，不出现一半新一半旧。

---

## 8. Commit 4：发送层加进度提示与伪流式

### 8.1 目标
先解决“前台像死了一样”的体感问题，不强求第一刀就把 provider 真流式彻底打通。

### 8.2 真实文件
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/output/sender.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/output/sender_adapter.py`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/src/plugins/yangyang/output/sender_adapter_factory.py`

### 8.3 本 commit 要做的事

#### A. `sender_adapter.py`
先补最小能力接口，例如：
- 发送短进度消息；
- 支持按 chunk 续发文本；
- 支持在不支持编辑消息时退化为多段发送。

#### B. `sender.py`
补一个最小调度层：
- 若 `llm_streaming_progress_notice_enabled=True`，在长文/工具后场景先发一句短消息；
- 若最终文本超阈值，按 `llm_streaming_fake_stream_chunk_chars` 切段发送；
- 发送间隔由 `llm_streaming_fake_stream_interval_ms` 控制；
- 若链路不支持 chunk，则降级为整段一次发。

#### C. `sender_adapter_factory.py`
只要需要，就补适配器能力探测：
- 是否支持编辑；
- 是否支持分段续发；
- 不支持则自动走最低保守路径。

### 8.4 推荐策略
第一刀先做两层：
1. **进度通知**：先告诉前台“在查，等我切两刀。”
2. **伪流式**：最终长文分段发送，而不是整段攒死。

### 8.5 可以先 stub 的部分
- 真流式 token 级推送可先不做；
- provider SSE / async stream 可留到下一轮；
- 消息编辑态若平台限制大，可直接退化为多段发送。

### 8.6 必须一次改通的部分
- 发送层不能因伪流式而破坏原有单段发送；
- 进度通知必须可开关；
- 分段发送必须保证顺序稳定；
- 工具型长回复至少能先出一句占位消息。

### 8.7 验收
- 长文场景先出现短提示，再出现正文；
- 正文能按 chunk 续发；
- 不启用新开关时保持原行为；
- 平台不支持时能安全降级。

---

## 9. Commit 5：smoke / 灰度 / 回滚

### 9.1 目标
确保这轮改动不是纸面完成，而是可以小步放量、随时回滚。

### 9.2 smoke 最小清单

#### Smoke 1：普通私聊
验证：
- 仍能正常回复；
- 日志里有 `timeout_bucket=normal`；
- 未开 streaming 时表现与旧版一致。

#### Smoke 2：owner 工具后收口
验证：
- 工具链跑完后，最终收口不再过早超时；
- 日志里能看到 `interaction_phase=tool_followup`；
- fallback 情况可观测。

#### Smoke 3：长文交付
验证：
- 走 `timeout_bucket=longform`；
- 若开启进度提示，前台先收到占位短消息；
- 长文可分段发送。

#### Smoke 4：关开关回退
验证：
- 关闭 `llm_timeout_bucket_enabled` 后回退旧 timeout；
- 关闭 `llm_streaming_enabled` / 伪流式相关开关后回退旧发送；
- 不需要改代码即可停火。

### 9.3 灰度顺序建议
1. 先只开 bucket 观测，不改默认超时；
2. 再只对 owner 私聊打开 `tool_followup / longform` bucket；
3. 再开进度提示；
4. 最后再开伪流式分段发送。

### 9.4 回滚策略
若出问题，按这个顺序回：
1. 先关 `llm_streaming_*`；
2. 再关 `llm_timeout_bucket_enabled`；
3. 如仍异常，再回退 `model_router.py` 签名改动对应 commit。

---

## 10. 这一轮别碰的东西
本轮先别顺手扩成大工程：
- 不做 `prompt_builder.py` 大重构；
- 不做 `owner_action_context_resolver.py` 状态改造；
- 不做 SSOT 全量落地；
- 不做工具回灌证据白名单正式版；
- 不做 provider 真 streaming 全家桶统一协议。

一句话：
**先把“超时硬死 + 前台没字”这两个狗屎点砍掉，再谈结构美学。**

---

## 11. 最终结论
如果现在开始动手，建议严格按下面顺序切：

1. **Commit 1**：补配置 schema
2. **Commit 2**：改 `model_router.py` 参数面和观测
3. **Commit 3**：改上层入口显式传 bucket
4. **Commit 4**：加进度提示和伪流式
5. **Commit 5**：做 smoke、灰度、回滚验证

最关键的一句：
**真正先该改的不是“流式炫技”，而是 router 的 timeout 参数化和上层显式 bucket 注入。**

这刀砍完，后面再接真流式、证据白名单、SSOT，才不会一路长尸山。
