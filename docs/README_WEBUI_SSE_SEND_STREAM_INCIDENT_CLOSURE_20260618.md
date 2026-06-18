# WEBUI SSE send_stream INCIDENT CLOSURE RECORD - 2026-06-18

日期：2026-06-18  
状态：正式结案留档 / PATCH PASS  
范围：NoneBot WebUI SSE 真桥、8080 HTTP 面、QQ 内嵌工作台相关链路

---

## 1. 文档目的

本档用于正式记录 2026-06-18 这次 WebUI `send_stream` SSE 断连后拖死 8080 HTTP 面的事故结论、补丁处置、验收结果与后续加固方向。

本档和其他记录文档职责区分如下：

- 《`PATCH_NOTES_send_stream_sse_guardrails.md`》：记录补丁设计与执行流程
- 《`README_WEBUI_SSE_RUNTIME_HANG_PRE_RESTART_RECORD_20260618.md`》：记录重启前运行态现场现象
- **本文档**：作为最终事故结论与正式留档版本

---

## 2. 事故摘要

本次事故表现为：

- WebUI / QQ 内嵌工作台链路建立 `POST /yy/api/chat/send_stream` 的 SSE 流后
- 若客户端中途断开、切页、关闭页面或连接异常中止
- 8080 上的 HTTP 面随后出现“能建立连接，但长时间不回包”的半死状态

事故影响并不局限于 SSE 单一路由，而是会连带拖累同进程下的普通 HTTP 接口，造成服务看似在跑、端口也在监听，但应用层请求处理显著退化。

---

## 3. 事故现象

### 3.1 运行态表征

在故障窗口内，观测到以下行为：

- 8080 本地 TCP 连接可以建立
- 请求数据可进入服务端 socket 缓冲区
- 但应用层长时间不返回 HTTP 响应
- `send_stream` 请求可能超时
- 普通 HTTP 路由也可能一起长时间无响应

这类表现对应的是：

**服务未退出，但 HTTP 处理面进入“半死不活”的挂起状态。**

### 3.2 影响路径

影响主要集中在：

- `/yy/api/chat/send_stream`
- 同进程下的普通 HTTP 接口健康性
- WebUI / QQ 内嵌页的连续使用体验

8787 前门在部分阶段仍可能快速返回 401 或鉴权拦截，但这不能代表其后端 8080 真正健康。

---

## 4. 根因判断

本次故障主因已确认如下：

**`send_stream` 的 SSE 生命周期管理存在缺口，客户端断连后，服务端流任务/发送过程未正确止血和收口，残留状态持续拖累了同进程 HTTP 服务面。**

具体病灶主要包括：

1. **断连感知不足**
   - 原实现缺少稳定的 `request.is_disconnected()` 断连检查
   - 客户端已关闭时，服务端仍可能继续等待或推进后续发送

2. **清理时机不稳**
   - 任务结束、异常结束、主动取消三类路径没有完全统一到稳定的 cleanup 行为
   - 断流后仍可能继续向事件队列投递内容

3. **收尾路径设计存在放大风险**
   - 原逻辑在 `finally` 清理阶段继续发送 `proxy_closed`
   - 这会把“清理动作”和“再次发送动作”缠在一起
   - 一旦连接已断，容易放大 ASGI send 关闭路径异常

4. **取消分支边界不够硬**
   - `asyncio.CancelledError` 未被当作独立的正常取消边界处理
   - 会增加流关闭路径误报、误堆积或异常上浮的风险

---

## 5. 已实施处置

已对 `src/plugins/yangyang/__init__.py` 中 `/yy/api/chat/send_stream` 实施 SSE 守卫补丁，核心动作如下：

- 在 `_event_stream()` 主循环增加 `await request.is_disconnected()` 检查
- 客户端断开后立即记录并退出流循环
- 在清理阶段先 `finished.set()`，再取消后台模型任务
- 为 `_run_model_call()` 增加 `asyncio.CancelledError` 显式处理分支
- 为 `_on_stream_delta()` 及模型调用成功回填增加 `finished.is_set()` 守卫
- 不再在 `finally` 中发送 `proxy_closed`
- `proxy_closed` 仅在正常、且客户端未断开的收尾场景下发送

本次处置目标不是重写整条链路，而是做**最小有效止血修复**，优先压制“断连后残留 SSE 把 HTTP 面拖进僵局”的风险。

---

## 6. 回归与验收结果

本次补丁已完成静态与运行态验收，结果如下。

### 6.1 前置检查

| 检查项 | 结果 |
|--------|------|
| `py_compile` | PASS |
| `pytest test_send_stream_sse_guardrails.py` | 3/3 PASS |

### 6.2 普通 HTTP 面

| 端点 | 结果 |
|------|------|
| `/openapi.json` | HTTP 404 |
| `/` | HTTP 404 |
| `/yy/api/model/status` | HTTP 200, 9ms |

说明：

- `/openapi.json` 与 `/` 返回 404 不构成本次事故失败信号
- 关键在于 **HTTP 面能快速返回，而不是挂起无字节**
- `/yy/api/model/status` 快速 200，说明服务面已恢复健康响应能力

### 6.3 SSE 主桥正常流

已验证：

- `proxy_open`
- `session_id`
- `plain` 逐字 delta
- `agent_stats`
- `end`

全链路正常回流，无报错，完整跑通。

### 6.4 SSE 断连场景

已验证：

- 断连后 `/yy/api/model/status` 仍返回 HTTP 200
- 断连后再次发起 SSE，可正常创建新 session 并正常回流

这说明：

**客户端断连后，8080 不再被残留 SSE 拖死。**

### 6.5 日志异常关键词检查

本轮验收中，以下异常关键词均为 0：

| 关键词 | 出现次数 |
|--------|---------|
| `streaming response error` | 0 |
| `ASGI send exception` | 0 |
| `task destroyed but pending` | 0 |
| `CancelledError` 上浮 | 0 |
| 新 `traceback` / `import error` | 0 |

---

## 7. 事故结论

本次问题不是模型能力故障，不是主链路服务整体失效，也不是单纯的网络连通性问题。

最终可定性为：

**Web SSE 真桥在客户端异常断开后的生命周期管理缺陷，导致残留流状态拖累 8080 HTTP 面，形成“可连接但不回包”的半死状态。**

补丁已经命中主因，验收结果表明：

- 正常流可跑通
- 断连后可正确收口
- 再次建流正常
- 普通 HTTP 面不再被残留连接拖入僵局
- 日志侧未出现新的关闭路径异常

结论：

**PATCH PASS，本次事故可正式结案。**

---

## 8. 影响与边界说明

本次修复已实锤解决当前主故障，但仍需保持以下工程边界意识：

1. 本次修复针对的是 `send_stream` SSE 断连/清理路径
2. 其目标是压制最核心的 HTTP 面半死问题
3. 不代表前端、代理层、WebView 生命周期、网关策略等外围链路已经一次性全部免疫

也就是说：

**主尸变体已经砍死，但外围巡检仍要继续。**

---

## 9. 后续加固清单

### 9.1 P0：纳入常规回归

建议把以下场景列为固定回归项：

1. SSE 正常建流、持续输出、正常结束
2. SSE 中途断连后服务端收口验证
3. 断连后立即重建新流验证
4. 断连后普通 HTTP 端点快速返回验证
5. QQ 内嵌页 / 8787 / 本地工作台的真实链路复验

### 9.2 P1：补充观测指标

建议新增或统一以下观测：

- 活跃 SSE 连接数
- SSE 新建次数
- 客户端断连次数
- cleanup 执行次数
- cancel 次数
- send 异常次数
- 流结束原因分类
- 平均流持续时长

### 9.3 P1：日志结构化

建议在 `send_stream` 关键路径记录结构化字段：

- `session_id`
- `request_id`
- `disconnect_detected`
- `cleanup_done`
- `stream_closed_normally`
- `cancel_reason`
- `exception_class`

### 9.4 P2：外围链路复核

建议继续巡检：

- 8787 / WebUI 前端是否有重复建流
- 页面销毁时是否正确 abort/close
- QQ 内嵌页切后台、回退、切页时是否残留旧连接
- 代理层 keep-alive / timeout / connection close 策略是否会放大问题

---

## 10. 最终状态

当前结论：

- 补丁已落地
- 回归测试通过
- 运行态验收通过
- 日志无新增异常关键词
- 可继续后续工程工作

一句话收口：

**这次不是靠玄学重启混过去，而是 SSE 断连收尾这刀真砍中了。**

done。♂爽
