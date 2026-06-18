# M2.2 Explicit Context Memory Stable Candidate (2026-06-04)

## 定位

这是 M2.2 显式上下文记忆链路的整合交付包，汇总 A0 -> B2-A 当前稳定成果。

小包仍保留在 `dist/patches/` 作为施工记录与回滚点；本包用于交付/灰度部署。

## 当前稳定状态

已通过开发仓库定向测试：

```text
109 passed in 0.97s
```

覆盖测试：

```bash
python3 -m pytest -q \
  tests/test_memory_phase_c.py \
  tests/test_provider.py \
  tests/test_explicit_memory.py \
  tests/test_recent_message_records.py \
  tests/test_context_resolver.py \
  tests/test_topic_boundary_resolver.py
```

## 已启用的生产能力

### 1. owner 私聊显式直写

```text
记一下：xxx
记录一下：xxx
存档一下：xxx
```

行为：

- owner 私聊拦截；
- 直接写入 explicit memory；
- `source=owner_command`；
- 本地回复，不进入 LLM；
- 查询/审计不写入。

### 2. owner 私聊上下文型显式记忆（规则版）

```text
把刚才我们的讨论内容记一下
刚才那个也记一下
上面那段存档
这个结论记录一下
```

行为：

- 读取 owner 私聊 recent messages；
- 使用 A3.1 规则版 recent context resolver 生成候选 payload；
- pending confirmation；
- 用户确认后写入 `source=explicit_context_resolved`；
- 不写命令本身；
- 不混 bot 回复、确认词、旧主题；
- 日志格式无 `%s/%d` 残留。

### 3. pending 确认/取消

pending 存在时：

```text
确认 / 是 / 好 / 对 / 可以
```

写入。

```text
取消 / 不用 / 算了 / 别记
```

取消。

无 pending 时确认词放行，不被误拦截。

### 4. 群聊边界

本包不启用群聊显式记忆：

- 群聊 `记一下xxx` 不写主脑；
- owner 群聊 @ 也不触发主脑显式写入；
- 群聊闸门不变。

## 已实现但默认不启用的能力

### B2-A topic boundary resolver hook

`handle_explicit_memory_message(...)` 支持可选参数：

```python
topic_boundary_model_call=None
```

默认 `None`，生产仍走 A3.1 规则版。

测试可注入 fake model call，走 B1 `topic_boundary_resolver.py`：

- resolved -> pending topic boundary confirmation；
- ambiguous / insufficient_context -> 追问，不回退规则版，避免错记；
- invalid_model_output / model_error -> 回退 A3.1 规则版。

注意：本包**不接真实 LLM**，不接 provider，不改 runtime_config。

## 新增/修改模块

### `src/plugins/yangyang/memory/store.py`

新增 recent records 只读查询接口：

```python
MemoryStore.get_recent_message_records(...)
```

返回字段包含：

```text
msg_id / uid / nick / group_id / channel / text / raw_content / is_bot / created_at
```

用于 evidence/context_range。

### `src/plugins/yangyang/memory/explicit_memory.py`

显式记忆 intent router：

- write / query / audit / confirm / cancel / none；
- direct write；
- contextual write 标记：`needs_context_resolution`、`context_markers`、`context_hint`。

### `src/plugins/yangyang/memory/context_resolver.py`

A3.1 规则版 recent context resolver：

- 仅作为止血/兜底；
- 排除 bot 回复、确认词、命令文本、handler确认回复、纯指代；
- 轻量话题边界；
- 生成 pending payload。

重要边界：固定 1-3 条 owner 实质消息不是最终方案，真实讨论边界后续应由 LLM/语义边界评估。

### `src/plugins/yangyang/memory/topic_boundary_resolver.py`

B1 mockable topic boundary resolver：

- 构造模型 messages；
- 解析 JSON；
- 校验 `used_msg_ids/start_msg_id/end_msg_id` 必须在窗口内；
- 处理 ambiguous/insufficient/bad JSON/model error；
- payload 限长；
- 目前仅测试注入 fake model，不接真实 LLM。

### `src/plugins/yangyang/memory/explicit_handler.py`

接入 owner 私聊显式记忆主流程：

- direct write；
- contextual pending；
- pending confirm/cancel；
- 可选 topic boundary hook；
- 默认生产不启用真实模型。

### `src/plugins/yangyang/__init__.py`

包含 M2.1 handler 接入点：

- 在 `store.record_message` 之后；
- 在 prompt/LLM 前；
- handled 后本地发送并 return。

## 未实现 / 不在本包范围

- 真实 LLM provider adapter；
- runtime_config 开关；
- memory grounding；
- alias/entity resolver；
- 群聊显式记忆；
- 群友黑料库；
- 亲密互动双层日志；
- cron/Ops；
- 主动陪伴；
- Phase D。

## 部署方式

本包带顶层目录，部署到宿主仓库：

```bash
tar -xzf dist/patches/yangyang_m2_2_explicit_context_memory_stable_20260604.tar.gz \
  -C /opt/yangyang_nonebot \
  --strip-components=1
```

本包不包含、不覆盖 `runtime_config.json`。

## 宿主机灰度建议

1. 部署前备份：
   - `src/plugins/yangyang`
   - `tests`
   - `src/plugins/yangyang/data/memory/long_term/memories.jsonl`
2. 覆盖本包。
3. 跑定向测试：

```bash
python3 -m py_compile \
  src/plugins/yangyang/__init__.py \
  src/plugins/yangyang/memory/store.py \
  src/plugins/yangyang/memory/explicit_memory.py \
  src/plugins/yangyang/memory/explicit_handler.py \
  src/plugins/yangyang/memory/context_resolver.py \
  src/plugins/yangyang/memory/topic_boundary_resolver.py \
  tests/test_memory_phase_c.py \
  tests/test_provider.py \
  tests/test_explicit_memory.py \
  tests/test_recent_message_records.py \
  tests/test_context_resolver.py \
  tests/test_topic_boundary_resolver.py

python3 -m pytest -q \
  tests/test_memory_phase_c.py \
  tests/test_provider.py \
  tests/test_explicit_memory.py \
  tests/test_recent_message_records.py \
  tests/test_context_resolver.py \
  tests/test_topic_boundary_resolver.py
```

4. 真机验收：
   - `记一下：stable bundle 测试条目` -> direct write；
   - `你记得我昨天说了什么吗` -> 不写；
   - 先发一句上下文，再发 `把刚才我们的讨论内容记一下` -> pending payload 干净；
   - `确认` -> `source=explicit_context_resolved`；
   - 无 pending 时 `确认/好/是` 放行；
   - 群聊 `记一下xxx` 不写主脑；
   - C3.1 `我晚上喜欢打什么游戏` 仍命中；
   - 日志无 `%s/%d` 残留、无双回复、无异常。

## 安全边界确认

- 不包含 runtime_config；
- 不接真实 LLM；
- 不接 MiniMax/GPT/provider；
- 不扩大群聊注入；
- 不开启群聊主动；
- 不改群聊闸门、owner gate、loop guard、kill switch；
- 不改 C1 被动写入语义；
- 不操作真实数据；
- 不做 cron/Ops。

## 下一步建议

1. 宿主机部署 stable bundle 并灰度；
2. 继续 B2-B：真实 LLM provider adapter + 配置开关，但默认关闭，只 owner 私聊灰度；
3. 后续 B/C：LLM topic boundary、memory grounding、alias/entity resolver；
4. 再后续：群聊显式记忆 / 群友黑料库；
5. 最后再做 M2.3 亲密互动双层日志。
