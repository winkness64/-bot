# M2.2-A3.1 Context Filter + Logging Fix (2026-06-04)

## 基线

基于 M2.2-A3 Contextual Handler Integration：

- A3 主链路已在宿主机灰度通过：contextual write -> pending -> confirm -> `source=explicit_context_resolved`。
- 本包只修复 A3 灰度暴露的问题，不新增大功能。

## 修复内容

### 1. Recent Context Resolver 降噪

A3 真机发现 payload 过宽，混入旧主题、bot 回复、短确认词和较早上下文。本包对规则版 resolver 做了止血型降噪：

- 默认排除 `is_bot=True` 的 bot 回复，避免把 bot 的复读/情绪语气写入 payload。
- 排除短确认/控制词：`确认 / 好 / 是 / 嗯 / 对 / 可以 / 取消 / 不用 / 算了` 等。
- 排除当前显式命令文本。
- 排除 handler 确认回复：`记好了，阿漂。`、`好，已经记录。`、`阿漂，是要记录为...` 等。
- 排除纯命令味/纯指代文本。
- 遇到 owner 短确认/控制词、handler确认、纯命令味文本时，作为轻量话题边界清空之前候选，避免旧主题穿过确认流混入最新 payload。
- 实际候选仍为规则版临时策略：最近 1-3 条 owner 实质消息；这只是 A3.1 降噪止血，不是最终讨论边界方案。

### 2. pending_context 日志格式修复

修复 A3.1 半成品中 `logger.info("...{}...", args...)` 在当前 logging 环境下触发：

```text
TypeError: not all arguments converted during string formatting
```

现在改为 f-string/预格式化字符串，不再有 `%s/%d` 或 `{}` + args 残留。

## 明确不是最终方案

阿漂确认：固定取 1-3 条只是规则版止血和测试策略。真实“刚才/那段/我们的讨论”边界可能跨 3 轮、6 轮、15 轮甚至更长。后续应进入 LLM/语义边界评估：

- 给 LLM 最近 20-50 条或 30-60 分钟候选窗口；
- 输出结构化 JSON：`ok/start_msg_id/end_msg_id/used_msg_ids/payload/confidence/reason`；
- 不确定时追问，不直接写入；
- 后续再叠加 memory grounding / alias resolver。

## 测试结果

```bash
python3 -m py_compile \
  src/plugins/yangyang/memory/context_resolver.py \
  src/plugins/yangyang/memory/explicit_handler.py \
  tests/test_context_resolver.py \
  tests/test_explicit_memory.py \
  tests/test_recent_message_records.py \
  tests/test_memory_phase_c.py \
  tests/test_provider.py
```

通过。

```bash
python3 -m pytest -q \
  tests/test_memory_phase_c.py \
  tests/test_provider.py \
  tests/test_explicit_memory.py \
  tests/test_recent_message_records.py \
  tests/test_context_resolver.py
```

结果：

```text
88 passed in 0.88s
```

`explicit_handler.py` / `context_resolver.py` grep `%s|%d`：无残留。

## 覆盖方式

本包带顶层目录，覆盖时使用：

```bash
tar -xzf dist/patches/yangyang_m2_2_a3_1_context_filter_logging_fix_20260604.tar.gz \
  -C /opt/yangyang_nonebot \
  --strip-components=1
```

本包不包含、不覆盖 `runtime_config.json`。

## 宿主灰度步骤建议

1. 部署前备份当前代码与长期记忆文件。
2. 覆盖本包，重启服务。
3. 跑定向测试：
   - `tests/test_memory_phase_c.py`
   - `tests/test_provider.py`
   - `tests/test_explicit_memory.py`
   - `tests/test_recent_message_records.py`
   - `tests/test_context_resolver.py`
4. 真机复测：
   - 先制造旧主题 + 确认词 + bot 回复 + 新 owner 主题；
   - 发送 `把刚才我们的讨论内容记一下`；
   - 期望 pending payload 只包含最新 owner 实质内容，不包含旧主题、`确认`、bot 回复；
   - 发送 `确认` 后写入 `source=explicit_context_resolved`；
   - 检查日志无 `%s/%d` 残留，无 logging TypeError。

## noisy 测试记忆清理建议

A3 灰度产生的 noisy 记忆不建议保留：

```text
mem_explicit_039f2cde59717d9d
```

建议在宿主机备份 `long_term/memories.jsonl` 后，手动删除或修正该条；不要保留其过宽 value，避免污染后续回忆。

本包不会直接操作宿主真实数据。

## 未触碰禁区

- 未改 runtime_config，包内不含 runtime_config。
- 未接 LLM/MiniMax/GPT。
- 未做 memory-grounding / alias/entity resolver。
- 未做群聊显式记忆。
- 未做亲密互动日志。
- 未改群聊闸门、owner gate、loop guard、kill switch。
- 未扩大群聊注入，未开启群聊主动。
- 未改 C1 被动写入语义。
- 未清洗/修改真实数据文件。
- 未做 cron/Ops。
- 未操作宿主机生产服务。

## 下一步

- 宿主机 A3.1 灰度；
- 清理/修正 noisy 测试记忆；
- 后续进入 M2.2-B：LLM topic boundary / memory grounding / alias resolver 设计与实现。
