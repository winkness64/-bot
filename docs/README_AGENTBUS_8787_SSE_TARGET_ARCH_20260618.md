# README_AGENTBUS_8787_SSE_TARGET_ARCH_20260618.md

## 背景

本轮开发已经确认：

- `i_line p0` 在当前阶段主要只剩过渡诊断价值，主战意义已明显下降。
- NoneBot 主插件侧已经具备内部流式接口：`POST /yy/api/chat/send_stream`。
- 8787 WebUI 本地 NoneBot 分支当前仍停留在 `probe_fallback` 包壳阶段。
- 8787 总控的 SSE 形态，不应再被理解为“某个聊天功能的流式优化”，而应视为未来 Agent Bus 的统一事件总线外壳。

因此，本文件用于正式留档：**8787 总控 SSE = 未来 Agent Bus 的前台统一事件壳；NoneBot `/yy/api/chat/send_stream` = 首个接入该总线形态的本地事件生产者。**

---

## 一句话结论

**未来主形态不是继续强化 `i_line p0`，而是把 8787 总控 SSE 做成统一事件入口，让 NoneBot、AstrBot、后续 worker / validator / collector 都能以同类事件流接入。**

---

## 当前工程判断

### 1. `i_line p0` 应退居二线

`i_line p0` 历史上承担过：

- 只读健康检查
- 内部桥接验证
- Agent Bus 早期探路
- fallback / probe 级诊断能力

但现在继续围绕 `p0` 堆功能，收益已经明显变低。

更合理的定位是：

- 兼容层
- 诊断壳
- 只读探针
- 过渡保底入口

不再作为后续总线主战结构。

### 2. 真主线已经切到 8787 总控 SSE

当前真正有战略价值的，不是“某个 bot 会不会流式回复”，而是：

- 8787 是否能稳定承载统一 SSE 事件协议
- 不同后端是否都能挂到这套协议下
- 前端是否只认事件流，不再理解各后端内部差异

这意味着 8787 的定位应升级为：

- 总控台
- 舰桥
- 前台统一入口
- Agent Bus 事件汇聚层

### 3. NoneBot 已具备成为标准事件生产者的条件

当前 NoneBot 侧已具备：

- localhost-only 内部桥接口
- `text/event-stream` 输出能力
- 基于 router streaming callback 的增量事件吐出能力
- 与 8787 现有消费模型相近的最小事件骨架

因此它已经可以作为第一批“总线事件生产者”接入 8787。

---

## 目标架构

### 目标分层

#### 第一层：8787 统一入口层

8787 对前端暴露统一聊天 / 事件入口，例如：

- `/api/chat/send`
- `/api/chat/send_stream`

前端只和 8787 对话，不直接感知后端实例差异。

#### 第二层：8787 路由分发层

8787 负责根据实例类型、配置或策略，把请求分流到不同后端：

- AstrBot
- NoneBot
- 后续 AgentBus worker
- validator / collector / factory 相关执行节点

#### 第三层：后端事件生产层

各后端尽量输出统一语义的 SSE 事件：

- 文本增量
- 会话标识
- agent 元信息
- 状态阶段
- 工具 / 步骤事件
- 收尾事件
- 错误事件

#### 第四层：前端事件消费层

前端只消费标准事件，不理解：

- 某个后端内部路由怎么写
- 某个模型怎么回退
- 某个 worker 如何执行
- 某个 bot 是否需要额外包壳

这样后端可以持续换血，而前端协议保持稳定。

---

## 为什么说 8787 SSE 才是未来 Agent Bus 的真正形态

### 1. 它天然适合承载“持续事件”而不是“一次性结果”

Agent Bus 的本质不是返回一个 JSON，而是持续吐出运行过程中的多类信号，例如：

- 文本输出
- 工具调用状态
- agent 阶段推进
- worker 切换
- validator 结果
- collector 汇总
- 错误 / 中断 / 收尾状态

SSE 很适合承载这类有时间顺序的事件流。

### 2. 它可以统一聊天、诊断、工厂运行和日志旁路观测

8787 当前就已经不是单一聊天页面，而是总控式入口，具备：

- 工厂观察
- 日志接入
- Bot 侧观测
- AstrBot 透传
- 未来继续接管更多后端事件流的扩展空间

因此它更像舰桥，而不是单功能聊天框。

### 3. 它能把“后端实现差异”压扁成“前端统一事件协议”

只要 8787 对前端保持统一 SSE 事件语义，那么后端来自：

- NoneBot
- AstrBot
- worker factory
- validator
- collector

对前端而言都只是“谁在产流”的区别，而不是“协议得重写”的区别。

---

## 当前已确认的现实状态

### 1. NoneBot 真流接口已在位

已有内部接口：

- `POST /yy/api/chat/send_stream`

接口定位：

- localhost-only
- internal bridge only
- 面向 8787 这类本地总控代理

最小事件骨架当前为：

- `proxy_open`
- `session_id`
- `plain`
- `agent_stats`
- `end`
- `error`
- `proxy_closed`

这已经足够作为 8787 本地 NoneBot 分支的第一版真流接入面。

### 2. 8787 在役脚本当前仍是“假流”

当前在役 8787 脚本已定位到：

- `/root/data/data/workspaces/scripts/agentbus_factory_webui.py`

已确认其本地 NoneBot 分支逻辑为：

- 命中 `NONEBOT_LOCAL_INSTANCES`
- 进入 `proxy_nonebot_local_chat(...)`
- 上游调用 `'/yy/api/model/probe_fallback'`
- 再由 8787 自己手工拼出 SSE 事件返回前端

这说明：

- 前端虽然看到 SSE
- 但上游并不是 NoneBot 真流
- 而是 8787 对一次性结果做了事件包装

因此它本质上仍是过渡假腿。

### 3. 当前最关键卡点已经非常明确

卡点不在：

- QQ / OneBot11 适配器
- 前端是否支持流式显示
- `i_line p0` 是否还要再补一层

真正卡点在：

**8787 在役脚本尚未把本地 NoneBot 分支切换到 `/yy/api/chat/send_stream` 真流模式。**

---

## 设计原则

### 原则 1：8787 负责总线，不负责伪造业务结果

8787 应尽量只做：

1. 收请求
2. 选后端
3. 转发上游 SSE chunk
4. 必要时做最薄的协议兼容层

尽量不要在 8787 中：

- 冒充上游生成聊天结果
- 手工拼装大量业务事件
- 让总控承担后端脑子

一句话：**总控做总线，不做人格脑。**

### 原则 2：后端负责产标准事件

谁处理业务，谁负责产事件。

对于 NoneBot，这意味着：

- 真正执行聊天 / 路由 / 回答生成的地方在 NoneBot
- 对应的标准 SSE 事件也由 NoneBot 直接吐出
- 8787 只转发，不二次发明业务语义

### 原则 3：`probe_fallback` 退回诊断定位

`/yy/api/model/probe_fallback` 后续更适合用于：

- 模型可用性检查
- fallback 链探针
- 只读诊断
- 管线排障

不再承担正式聊天流入口职责。

### 原则 4：前端协议优先稳定

能复用现有 AstrBot / WebUI 已接受的 SSE 事件语义，就尽量复用。

目标是：

- 前端尽量不重写
- 8787 只补最小兼容
- 后端逐步对齐事件契约

---

## 8787 → NoneBot 的目标改造

### 现状

当前本地 NoneBot 分支路径：

- 8787 接收前端请求
- 路由到本地 NoneBot 分支
- 调用 `/yy/api/model/probe_fallback`
- 8787 自己手工构造 SSE
- 前端看到的是“包装后的流”

### 目标

应改造成：

- 8787 接收前端请求
- 路由到本地 NoneBot 分支
- 以 `Accept: text/event-stream` 调用 `POST /yy/api/chat/send_stream`
- 持续读取上游 SSE chunk
- 原样透传给前端

### 改造后效果

改造完成后：

- NoneBot 成为真流上游
- 8787 成为统一总控转流层
- 前端继续消费同类 SSE 事件
- `probe_fallback` 不再冒充聊天主入口

---

## 最小落地方案

### Phase A：把本地 NoneBot 分支切真流

目标：

- 在 8787 脚本中定位并修改 `proxy_nonebot_local_chat(...)`
- 把上游目标从 `/yy/api/model/probe_fallback` 改为 `/yy/api/chat/send_stream`
- 保留 `Accept: text/event-stream`
- 透传上游 chunk
- 删除大部分手工 SSE 拼装逻辑

验收标准：

- 8787 前端发起本地 NoneBot 聊天时，能够持续收到 NoneBot 真流事件
- 事件顺序正常
- 前端无需额外重写协议

### Phase B：抽象统一后端流适配层

后续可把 8787 内各类上游流源整理为类似：

- `stream_from_astrbot(...)`
- `stream_from_nonebot(...)`
- `stream_from_agentbus(...)`

但对前端都统一返回 SSE。

### Phase C：把 Agent Bus 执行节点正式接进来

当 worker / validator / collector / factory 逐步标准化后，8787 可继续作为：

- 统一前台入口
- 多后端流汇聚壳
- 观测与调度总台

这时 NoneBot 只是接入者之一，而不是整个系统唯一中心。

---

## 对后续文档和开发的影响

### 1. 关于 `i_line p0`

后续文档不再把 `i_line p0` 视作主战结构。

推荐口径：

- `i_line p0` 是过渡诊断层
- 可保留，但不继续堆主功能

### 2. 关于 8787

后续文档应统一把 8787 理解为：

- 总控台
- 舰桥
- Agent Bus 统一事件壳

而不是“给某个 bot 做流式聊天页面”。

### 3. 关于 NoneBot

后续应把 NoneBot 视作：

- 本地人格 / 执行节点之一
- 标准 SSE 事件生产者之一
- 总线接入方，而非唯一前台

---

## 建议的后续施工顺序

1. 修改 8787 在役脚本本地 NoneBot 分支，切到 `/yy/api/chat/send_stream`
2. 做一次端到端真流自测，确认前端无感切换
3. 记录实际 SSE 事件序列，沉淀统一事件契约
4. 逐步抽象 AstrBot / NoneBot / 后续 AgentBus 的流适配层
5. 再推进 validator / collector / factory 等事件流接入

---

## 本文档用途

本文档是 2026-06-18 阶段留档，作用是：

- 给后续开发确定主航向
- 防止再把精力浪费在 `p0` 壳子继续加补丁
- 明确 8787 SSE 的战略定位
- 作为后续 8787 在役脚本改造的设计依据

---

## 关联文档

- `docs/README_WEBUI_SSE_STREAMING_INVESTIGATION_20260618.md`
- `docs/README_WEBUI_SSE_STREAMING_CHECKPOINT_20260618.md`
- `docs/webui_work_guide.md`

---

## 最终定性

**8787 总控的 SSE，就是未来 Agent Bus 的真正前台形态。**

**NoneBot `/yy/api/chat/send_stream` 不是临时修补，而是第一根正式焊上总线的本地事件输出口。**
