# M2.2-B2-B Async Topic Boundary Integrated Bundle (2026-06-04)

## 定位

这是 M2.2-B2-B async topic boundary 基础设施 + `__init__.py` 最小接入的整合包。

它包含：

- async topic boundary resolver；
- async provider adapter；
- config gate helper；
- async explicit handler wrapper；
- `__init__.py` 主流程最小接入 async wrapper。

本包用于在宿主机上部署“默认关闭的 async topic boundary 基础设施”。

重要：本包不启用真实 LLM，不修改 runtime_config。只要 `memory_topic_boundary_enabled` 未显式为 true，生产行为仍回退 A3.1 规则版。

## 测试结果

```text
146 passed
```

定向测试范围：

```bash
python3 -m pytest -q \
  tests/test_memory_phase_c.py \
  tests/test_provider.py \
  tests/test_explicit_memory.py \
  tests/test_recent_message_records.py \
  tests/test_context_resolver.py \
  tests/test_topic_boundary_resolver.py \
  tests/test_topic_boundary_provider.py \
  tests/test_topic_boundary_gate.py \
  tests/test_async_explicit_handler.py
```

## 当前生产默认行为

配置缺失或 disabled 时：

- owner 私聊 `记一下：xxx` -> direct write；
- owner 私聊 `把刚才讨论内容记一下` -> A3.1 规则版 recent context resolver + pending；
- query/audit 不写；
- 群聊不写主脑；
- 不调用真实 LLM；
- 不调用 topic boundary router。

## 已接入但默认关闭的能力

`src/plugins/yangyang/__init__.py` 已最小接入：

```python
await handle_explicit_memory_message_async(...)
```

传入：

- runtime config mapping；
- 主流程 router 对象。

但 gate 默认 disabled，因此 router 不会被 topic boundary 调用。

## 模块说明

### `topic_boundary_resolver.py`

提供 sync/async topic boundary resolver，负责解析模型 JSON，校验 used_msg_ids/start/end，处理 ambiguous/invalid/model_error。

### `topic_boundary_provider.py`

将现有 async `ModelRouter.call(...)` 包装为：

```python
async model_call(messages) -> str
```

支持 timeout 与返回文本提取。

### `topic_boundary_gate.py`

纯配置 gate：

- 默认关闭；
- owner 私聊 only；
- 群聊永远 disabled；
- 数值配置安全 clamp；
- 不读取、不写入真实 runtime_config。

### `explicit_handler.py`

新增 async wrapper：

```python
handle_explicit_memory_message_async(...)
```

策略：

- config disabled/router None -> 回退同步 A3.1；
- enabled + router + owner private contextual write -> async topic boundary；
- resolved -> pending；
- ambiguous/insufficient -> 追问，不回退；
- invalid/model_error -> 回退 A3.1。

### `__init__.py`

主流程 explicit memory 接入点保持在：

- `store.record_message(...)` 之后；
- prompt/LLM 调用之前；
- handled 后 local send 并 return。

## 配置键（未来手动灰度用）

本包不写入 runtime_config，仅支持未来传入以下键：

```json
{
  "memory_topic_boundary_enabled": false,
  "memory_topic_boundary_private_enabled": true,
  "memory_topic_boundary_model_tier": "v4_flash",
  "memory_topic_boundary_max_records": 40,
  "memory_topic_boundary_max_payload_chars": 800,
  "memory_topic_boundary_min_confidence": 0.65,
  "memory_topic_boundary_timeout_seconds": 8,
  "memory_topic_boundary_fallback_on_invalid": true,
  "memory_topic_boundary_fallback_on_error": true,
  "memory_topic_boundary_fallback_on_ambiguous": false
}
```

## 部署方式

本包带顶层目录：

```bash
tar -xzf dist/patches/yangyang_m2_2_b2b_async_topic_boundary_integrated_20260604.tar.gz \
  -C /opt/yangyang_nonebot \
  --strip-components=1
```

本包不包含、不覆盖 runtime_config。

## 宿主灰度步骤

1. 部署前备份代码与 runtime_config。
2. 覆盖本包。
3. 不修改 runtime_config。
4. 跑定向测试，期望 146 passed。
5. 真机验证：
   - direct write；
   - contextual A3.1 pending + confirm；
   - query/audit 不写；
   - C3.1 回归；
   - 群聊不写主脑；
   - 确认 topic boundary keys 缺失/disabled 时没有真实模型调用。

## 未实现 / 不在本包范围

- 真实 LLM 灰度；
- runtime_config 写入或默认开启；
- memory grounding；
- alias/entity resolver；
- 群聊显式记忆；
- 群友黑料库；
- 亲密互动日志；
- cron/Ops。

## 下一步建议

- 宿主部署 integrated bundle，验证默认关闭下行为不变；
- 再做 B2-B3 owner 私聊真实模型小灰度，手动开启配置，严格小流量。
