# 8787 在役脚本最小改造方案（NoneBot 真 SSE 透传）

日期：2026-06-18  
状态：设计完成，待施工  
定位：给 8787 总控 WebUI 在役脚本做最小改造，使本地 NoneBot 分支从 `probe_fallback` 假流切换为 `/yy/api/chat/send_stream` 真 SSE 透传。

---

## 1. 背景结论

当前主线已经明确：

- **8787 总控 SSE** 是未来 Agent Bus 的统一前台事件壳。
- **NoneBot `/yy/api/chat/send_stream`** 已经具备标准 SSE 事件输出能力。
- **8787 在役脚本** 对本地 NoneBot 分支仍停留在 `probe_fallback` 包装阶段。
- `i_line p0` 与 `probe_fallback` 只适合继续保留为诊断/探针层，不应继续承担正式聊天主链路。

因此，本次施工目标不是重做前端，而是把 **8787 本地 NoneBot 分支改成真流透传**。

---

## 2. 当前现状

### 2.1 在役脚本

当前运行中的 8787 WebUI 脚本为：

`/root/data/data/workspaces/scripts/agentbus_factory_webui.py`

### 2.2 当前 NoneBot 本地分支行为

本地 NoneBot 分支命中后，会进入类似 `proxy_nonebot_local_chat(...)` 的逻辑，现状为：

1. 从请求消息中猜 `scope`
2. POST 到 NoneBot 的：
   - `/yy/api/model/probe_fallback`
3. 再由 8787 本地手工拼装 SSE 事件吐给前端，例如：
   - `proxy_open`
   - `session_id`
   - `plain`
   - `agent_stats`
   - `end`
   - `proxy_closed`

这条链路只能算“探针结果包装”，不是正式聊天流。

### 2.3 目标接口现状

NoneBot 侧已经有正式接口：

- `POST /yy/api/chat/send_stream`

该接口可以直接输出标准 SSE 事件流，事件语义已与 8787 现有前端消费模型基本对齐。

---

## 3. 本次改造目标

把 8787 本地 NoneBot 分支从：

- `probe_fallback` 请求
- 本地手工拼 SSE

改成：

- POST `/yy/api/chat/send_stream`
- 请求头使用 `Accept: text/event-stream`
- 8787 将上游 SSE chunk **原样透传** 给前端
- 不再自行编造 `plain/end/agent_stats` 等业务事件

一句话：

**8787 做总线，不做脑补。**

---

## 4. 设计原则

### 4.1 最小改动

本轮只改 **NoneBot 本地分支**，不重构全部后端适配层，不动前端协议。

### 4.2 前端无感

前端仍然消费现有 SSE 事件，不要求同步改前端。

### 4.3 总控只负责转发

8787 负责：

- 收请求
- 判断后端实例类型
- 发起上游 SSE 请求
- 原样转发流
- 在必要时补充网关级错误事件

不负责：

- 解析完整回答再重拼
- 模拟 agent 结果
- 把探针接口冒充正式对话

### 4.4 诊断链保留

`/yy/api/model/probe_fallback` 继续保留，但只作为：

- 模型可用性探针
- fallback 链诊断工具
- 只读调试入口

不再承担聊天主链路。

---

## 5. 最小施工点

以下描述为施工级别的最小补丁方向。

### 5.1 锁定入口

8787 现有聊天入口仍保留，例如：

- `/api/astrbot/chat/send`

其中命中 `NONEBOT_LOCAL_INSTANCES` 的分支，替换其内部实现即可。

### 5.2 替换本地代理函数

把当前 `proxy_nonebot_local_chat(...)` 这类函数中的核心调用替换为：

#### 旧逻辑

1. 整理消息
2. 猜 `scope`
3. POST `/yy/api/model/probe_fallback`
4. 读取 JSON 结果
5. 手工产出 SSE 事件

#### 新逻辑

1. 整理消息
2. 推导 `scope/session_id`
3. POST `/yy/api/chat/send_stream`
4. 请求头显式要求 `text/event-stream`
5. 使用流式读取
6. 上游 chunk 原样透传前端

### 5.3 请求头要求

建议至少带上：

- `Accept: text/event-stream`
- `Content-Type: application/json`

如上游需要鉴权，则沿用当前 NoneBot 本地调用所用鉴权头，不在本轮新增协议。

### 5.4 请求体最小字段

建议透传/整理为以下最小字段：

- `message` 或 `text`
- `scope`
- `session_id`
- 可选：`tier`
- 可选：`profile`

若 8787 前端已有稳定字段名，优先在网关侧做一次兼容映射，不要逼前端先改。

### 5.5 响应处理

目标行为：

- 上游返回什么 SSE chunk，8787 就往前端写什么 chunk
- 不做事件级重组
- 不做 JSON 级“总结后再输出”
- 尽量不改变 chunk 边界

### 5.6 错误处理

只有在网关级失败时，8787 才自行补发有限错误事件，例如：

- 上游连接失败
- 上游返回非 200
- 上游返回非流式内容
- 读取中途连接断开且未返回正常结束事件

此时可以输出一个最小 `error` 事件，再结束响应。

---

## 6. 推荐伪代码

以下为逻辑伪代码，不代表最终文件原文：

```python
async def proxy_nonebot_local_chat(request_payload):
    body = build_nonebot_stream_payload(request_payload)

    async with httpx.AsyncClient(timeout=None) as client:
        upstream = client.stream(
            "POST",
            f"{NONEBOT_BASE}/yy/api/chat/send_stream",
            headers={
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
                # 如果已有鉴权头，这里沿用
            },
            json=body,
        )

        async with upstream as resp:
            if resp.status_code != 200:
                yield sse_error("nonebot upstream status=%s" % resp.status_code)
                return

            ctype = resp.headers.get("content-type", "")
            if "text/event-stream" not in ctype:
                yield sse_error("nonebot upstream not sse")
                return

            async for chunk in resp.aiter_raw():
                if chunk:
                    yield chunk
```

核心思想只有一句：

**读原始 chunk，直接转发。**

---

## 7. 施工顺序建议

### 第一步：只改 NoneBot 本地分支

目标：

- 不动 AstrBot 分支
- 不动前端
- 不大规模抽象公共层
- 先把 NoneBot 真流跑通

### 第二步：补最小网关错误事件

只在确实需要时补：

- 连接失败
- 状态码异常
- Content-Type 异常

### 第三步：本地回归验流

验证前端看到的是连续增量，而不是一次性整包落地。

### 第四步：再考虑统一适配层抽象

后续可再整理成：

- `stream_from_astrbot(...)`
- `stream_from_nonebot(...)`
- `stream_from_agentbus(...)`

但这不是本轮最小施工的阻塞项。

---

## 8. 验收标准

改造完成后，至少满足以下检查点：

### 8.1 功能验收

- 8787 命中本地 NoneBot 实例时，能够获得实时流式输出
- 前端能持续收到 `plain` 增量事件
- 会话结束时能收到正常结束事件
- 不再依赖 `probe_fallback` 冒充聊天返回

### 8.2 协议验收

- 上游请求目标为 `/yy/api/chat/send_stream`
- 请求头包含 `Accept: text/event-stream`
- 8787 不再手工重组主业务 SSE 事件

### 8.3 体验验收

- 首包时间不明显劣化
- 输出过程中不是“憋一整段再吐”
- 前端无需同步大改即可正常消费

---

## 9. 建议测试用例

### 9.1 基础流式问答

发送普通问题，观察：

- 是否持续输出增量文本
- 是否能正常结束

### 9.2 长回答压力

发送需要较长输出的问题，观察：

- 中途是否断流
- 是否被网关缓存成整包

### 9.3 空消息/异常输入

观察 8787 是否返回受控错误，而不是直接 500 裸炸。

### 9.4 上游故障模拟

临时让 NoneBot 流接口不可达，观察 8787 是否：

- 返回明确 `error` 事件
- 正常收尾
- 不把连接挂死

---

## 10. 回滚方案

本轮改造的回滚应保持简单粗暴：

- 保留旧版 `proxy_nonebot_local_chat(...)` 逻辑片段
- 若新流式代理异常，直接切回：
  - `/yy/api/model/probe_fallback`
  - 本地手工 SSE 包装

即：

**先让真流上线，再保留一脚后退。**

---

## 11. 后续扩展方向

当 NoneBot 真流透传跑稳后，再继续推进：

1. 抽象统一后端流适配层
2. 为 Agent Bus worker/factory/validator 接入同一 SSE 外壳
3. 增加更丰富事件类型，例如：
   - `tool_start`
   - `tool_end`
   - `step_status`
   - `agent_route`
   - `debug_trace`（仅调试开关开启时）
4. 让 8787 真正成为多后端统一事件总控台

---

## 12. 最终定性

这次改造不是单纯“把一个接口名换掉”。

它的战略意义是：

- 让 **8787 总控 SSE** 从临时代理页，升级为 **Agent Bus 总线门面原型**
- 让 **NoneBot** 成为第一类标准事件生产者
- 让 `probe_fallback` 回归探针本位
- 为后续 worker factory / validator / collector 接入统一流协议打底

一句话收口：

**先把 8787 → NoneBot 真 SSE 透传焊稳，后面的 Agent Bus 才有统一外壳可长。**
