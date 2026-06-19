# M2.2-A3 Contextual Handler Integration (2026-06-04)

## 基线

基于 M2.2-A2 Recent Context Resolver Core：

- A0 Recent Message Access Layer SHA256=`7ef6ccf0c84052aa60ee062e5650407e243cc9faebb4e1456ebd94d29b9c4928`
- A1 Contextual Write Detector SHA256=`86fbdfd2007c007d0849ce5c542e1612e46acf0a04d2baf1bef9349721128df0`
- A2 Recent Context Resolver Core SHA256=`c9b9cc3f3d437936470e1bbf45126d6429402ed463c94824ec71f52256eaf125`

## 实现内容

本补丁把 A2 规则版 `resolve_recent_context_for_explicit_write(...)` 接入 `explicit_handler` 的 owner 私聊 pending 流程：

1. 仅 owner 私聊、且 `intent.intent == "write"`、`intent.needs_context_resolution is True` 时进入 contextual 分支。
2. 使用 A0 `MemoryStore.get_recent_message_records(...)` 读取当前 owner 私聊 recent records：
   - `channel="private"`
   - `uid=<owner user_id>`
   - `session_id="private:<user_id>"`
   - `limit=16`
   - 优先 `exclude_msg_id=<current msg_id>`，无 msg_id 时尝试 `before_ts=<current timestamp>`。
3. 调用 A2：
   - `resolve_recent_context_for_explicit_write(intent, command_text, recent_records, max_messages=8, max_payload_chars=500)`
4. resolved 时：
   - 创建内存态 pending。
   - pending payload 使用 resolver 生成的 payload，不再使用原命令文本。
   - pending 保存 `resolver`、`used_msg_ids`、`context_range`、`resolution_reason`。
   - 回复 `漂♂总，是要记录为：“{payload}” 吗？`
   - action=`pending_context_confirmation`。
5. 用户确认 contextual pending 后：
   - 写入 explicit memory。
   - source=`explicit_context_resolved`。
   - evidence 文本保存 JSON，包含原命令、resolver、used msg ids、context_range、resolution_reason。
6. insufficient_context 时：
   - 不写入。
   - 不创建可确认写入 pending，并清除同 key 旧 pending，避免误确认。
   - 回复提示补充要记内容。
   - action=`context_insufficient`。

## 非目标 / 明确未做

- 规则版，不调用 LLM / MiniMax / GPT。
- 未做黑话 / alias / entity resolver。
- 未做 memory-grounded resolver。
- 未接群聊显式记忆。
- 未做亲密互动长日志。
- pending 仍为内存态，重启后丢失。
- 未改 runtime_config。
- 未改主流程 `__init__.py`。

## 回归保持

- direct write 不变：例如 `记一下：以后迁移包只发私聊` 仍 direct_write，source=`owner_command`。
- 普通非 contextual 中置信 pending 不变。
- query/audit 不写入。
- 无 pending 的 `确认/好/是` 放行。
- 群聊显式记忆仍 pass，不写主脑。
- 不扩大群聊注入，不开启群聊主动。
- 不改 C1 被动写入语义。

## 测试结果

语法检查：

```bash
python3 -m py_compile \
  src/plugins/yangyang/memory/explicit_handler.py \
  src/plugins/yangyang/memory/context_resolver.py \
  src/plugins/yangyang/memory/explicit_memory.py \
  src/plugins/yangyang/memory/store.py \
  tests/test_explicit_memory.py \
  tests/test_context_resolver.py \
  tests/test_recent_message_records.py \
  tests/test_memory_phase_c.py \
  tests/test_provider.py
```

结果：通过。

pytest：

```bash
python3 -m pytest -q \
  tests/test_memory_phase_c.py \
  tests/test_provider.py \
  tests/test_explicit_memory.py \
  tests/test_recent_message_records.py \
  tests/test_context_resolver.py
```

结果：`87 passed in 1.00s`。

## 覆盖方式

在仓库根目录解包覆盖：

```bash
tar -xzf dist/patches/yangyang_m2_2_a3_contextual_handler_integration_20260604.tar.gz -C /AstrBot/data/workspaces/default_FriendMessage_335059272/yangyang_nonebot_mvp
```

包内不包含 runtime_config，不会覆盖真实运行配置。

## 真机灰度步骤

1. owner 私聊先聊两三句形成上下文，例如：`今天 M2.2-A3 接入成功，下一步要做真机灰度`。
2. 发送：`把刚才我们的讨论内容记一下`。
3. 期望 bot 回复候选 payload，而不是原命令文本。
4. 发送：`确认`。
5. 检查 memories entry：
   - `source="explicit_context_resolved"`
   - `value` 为候选 payload。
   - evidence 包含原命令、resolver、used msg ids / context_range。
6. 测空上下文 / 刚重启场景：应提示补充内容，不创建可写 pending。
7. 回归：
   - direct write：`记一下：以后迁移包只发私聊`
   - C3.1/C4/provider 检索链路
   - 群聊边界：群聊 `记一下xxx` 不写主脑。
