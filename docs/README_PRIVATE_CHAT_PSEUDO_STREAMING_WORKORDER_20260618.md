# README_PRIVATE_CHAT_PSEUDO_STREAMING_WORKORDER_20260618

## 结论

当前 NoneBot 侧“私聊伪流式未生效”的主因已收束为：

1. 运行时总开关 `llm_streaming_enabled=false`，直接压死流式链路。
2. 群聊本身还有额外门禁，当前设计只允许私聊尝试伪流式。
3. `output/sender.py` 还存在最终整段补发/重复发送风险，但这不是“完全没流”的一号主因。

因此本单目标不是开启群聊流式，而是：

- **先恢复私聊伪流式**
- **需要重启服务后验证**
- **若私聊恢复，再补 sender 去重逻辑**

---

## 背景判断

已知前提：

- AstrBot 与 Nekor 链路可确认是流式。
- 中转站可先排除，不作为本单主怀疑对象。
- 当前问题应收敛在我们自有 NoneBot 侧“消费流 + flush + 发送”的实现链路。

进一步核对后，发现即使代码里存在私聊流式相关实现，只要运行时总开关关闭，provider 实际就不会按 stream 模式工作，后面的 `_on_direct_stream_delta` / `_flush_direct_stream_buffer` 也就失去意义。

---

## 本单目标

### P0 目标
恢复 **私聊伪流式** 能力，不处理群聊。

### P1 目标
确认重启后私聊链路是否真正按增量发送工作。

### P2 目标
若私聊已恢复，再修补最终发送阶段可能出现的整段补发问题。

---

## 执行步骤（给秧秧）

### 一、修改运行时配置

修改文件：

- `data/runtime_config.json`

检查并调整：

- `llm_streaming_enabled: true`

要求：

- 若当前为 `false`，改为 `true`
- 不顺手扩大其它流式范围，不要把群聊门禁一起放开
- 本轮只做最小必要修改

---

### 二、重启 NoneBot 服务

本项修复依赖重启加载运行时配置，光改文件不算生效。

要求：

1. 重启前确认配置文件已落盘。
2. 重启后先看服务是否正常拉起。
3. 若启动异常，先回报异常摘要，不要继续做业务验证。

---

### 三、重启后仅验证私聊

**本轮不要先测群聊。**

验证对象：

- owner 私聊 / 机器人私聊链路

验证预期：

1. 回复不应总是等整段完成后一次性吐出。
2. 应至少表现出分批输出/增量输出。
3. 若依旧严格整段返回，说明流式消费链路还有断点。

---

## 建议观察点

### 1）Router 层
重点确认：

- `allow_streaming` 传入值
- `_streaming_enabled()` 结果
- 最终 provider 调用是否真按 stream 方式发起

验收口径：

- 如果配置已开，但最终仍不是 stream 调用，问题还在 Router/Provider 对接层。

### 2）插件主流程
重点确认：

- `stream_state["enabled"]` 在私聊下最终是否为 true
- `_on_direct_stream_delta` 是否持续命中
- `_flush_direct_stream_buffer` 是否被实际调用

验收口径：

- 若 callback 从不命中，说明上游流没有真正喂到发送链。
- 若 callback 命中但不 flush，说明缓冲/节流条件卡死。

### 3）发送层
重点确认：

- `send_current_session` 发出去的是增量还是全量
- `Sender.send` 最终是否又补发整段

验收口径：

- 若前面已流，最后又整段再来一遍，就是尾段去重逻辑有坑。

---

## 临时日志建议

如需快速定点，建议加最小调试日志，优先只打长度、状态和命中次数，不要大量打印正文。

### 建议日志点

#### `core/model_router.py`
- `allow_streaming`
- 运行时 streaming 开关判定结果
- 最终 provider 是否以 stream 模式调用

#### `src/plugins/yangyang/__init__.py`
- `stream_state["enabled"]` 最终值
- `_on_direct_stream_delta` 命中次数
- 每次 delta 长度
- `_flush_direct_stream_buffer` 调用次数与发送长度

#### `src/plugins/yangyang/output/sender.py`
- `already_streamed` 长度
- `response_text` 原始长度
- postprocess 后长度
- 最终是否触发尾段发送
- 最终发送的是剩余 tail 还是整段文本

---

## 第二阶段修复项（私聊恢复后再做）

### sender 去重修补

当前风险：

1. 流式阶段发送的是原文。
2. 最终发送前先做 postprocess。
3. 再用 cleaned 文本去和 `already_streamed` 做前缀比较。
4. 一旦前缀在清洗中发生变化，就可能比较失效，导致整段补发。

### 修法方向

建议采用：

1. 先基于 **raw text** 扣除 `already_streamed`
2. 再对剩余 tail 做 postprocess
3. 只发送剩余 tail，不要先清洗再做整段前缀比较

本轮不要求大重构，只要先消除“流完后整段再发一次”的风险即可。

---

## 暂不处理项

本单明确不做以下内容：

1. 群聊伪流式放开
2. QQ 端“体感优化”类伪装
3. typing / 输入中态增强
4. 大规模改造 sender 架构
5. 中转站侧额外排查（本轮先排除）

---

## 验收标准

满足以下三条即可认为第一阶段通过：

1. **私聊出现可观察的增量输出**
2. **结尾不会整段重复发送**
3. **群聊保持现状，不引入额外刷屏或副作用**

---

## 回报时最少带回的信息

1. `llm_streaming_enabled` 是否已改为 `true`
2. 服务是否已成功重启
3. 私聊验证时是否出现增量输出
4. `_on_direct_stream_delta` 是否命中
5. 最终是否仍存在整段补发
6. 若失败，失败点卡在：
   - Router 未启流
   - callback 未命中
   - flush 未发生
   - sender 尾段重复发送

---

## 一句话执行摘要

**先开 `llm_streaming_enabled`，重启服务，只验私聊；若私聊恢复流式，再修 sender 的尾段去重，不碰群聊。**


---

## 2026-06-18 实际修复结果（补档）

本单后续已确认：最初判断并不完整，`llm_streaming_enabled` 不是这次 owner 私聊伪流式未生效的唯一根因。

最终落地的实际修复包含两处，且两处需要配合：

### 改动 1：流式 tool call 合并修复（`provider_openai_compat.py`）

原实现：

```python
tool_calls.extend(_normalize_tool_calls(...))
```

修正后：

- 按 `tool_call.index` 对流式 delta 逐块合并
- 将同一个 tool call 在多个 chunk 中拆开的 `id`、`name`、`arguments` 还原为完整对象

原因：

流式模式下，工具调用信息不是一次性到齐，而是分多个 chunk 逐步吐出。原来直接 `extend` 会把每个残缺 chunk 当成独立条目；随后 `_normalize_tool_calls` 遇到 `name=""` 的半成品条目会直接跳过，导致后续 `arguments` 片段丢失。

实际后果：

- 模型看起来像是发起了工具调用
- 但工具参数并未完整组装
- 写文件等工具在流式链路下会表现为“想调用但没有有效参数”
- 这也是此前 owner 私聊里工具整体失能的直接原因之一

### 改动 2：打开 I叔 owner 私聊流式（`__init__.py` 约第 1485 行）

```python
allow_streaming=False  ->  True
```

这一步的意义是：

- owner 私聊 native loop 分支此前实际被强制走非流式
- 改为 `True` 后，owner 私聊链路才真正进入流式模式

### 两处改动配合后的结果

修复后链路表现应为：

1. owner 私聊可正常进入流式输出
2. 工具调用在流式过程中按 `index` 合并为完整 tool call
3. `arguments` 不再丢失
4. `_normalize_tool_calls` 拿到的是完整可执行对象
5. 写文件、归档等工具调用恢复可用

### 本次事件最终结论

本次“owner 私聊伪流式未生效 / 工具调用异常”不是 sender 本身故障，也不只是运行时 streaming 总开关问题；更准确地说，是以下链式问题共同导致：

- owner 私聊链路被切到流式
- 但 provider 层流式 tool call delta 合并存在缺陷
- 导致工具调用 `arguments` 丢失
- 最终表现为工具在流式模式下集体失能，写文件等动作无法正常落盘

一句话归档：

**owner 私聊伪流式已恢复；根因是 native loop 分支开启流式后，暴露出 `provider_openai_compat.py` 的流式 tool call 合并缺陷。修复方式为：`allow_streaming=False -> True`，并将 tool call 改为按 `tool_call.index` 逐 delta 合并；修复后已验证可流式输出，且工具参数不再丢失，非 sender 本身故障。**
