# M2.1 Explicit Memory Handler · 2026-06-04

基于 M2 Explicit Memory Router v1：

- M2 v1 SHA256：`97c562fee0317b1ab4aeeabcfbef164e9f81ad467024bd25c2e08d07be0424d4`
- 前置状态：Memory M1 C3.1 Stable 已就绪；M2 Explicit Router v1 已就绪。

## 本包目标

正式收口 M2.1 owner 私聊显式记忆 handler 接入：在用户消息已入库后、PromptBuilder/ModelRouter/LLM 调用前处理明确的显式记忆命令；handler 命中时直接由 `Sender.send(...)` 回复并 `return`，不继续进入 LLM。

## 接入点

`src/plugins/yangyang/__init__.py`：

1. 导入 `handle_explicit_memory_message`。
2. 在 `store.record_message(msg, is_bot=False)` 之后获取 `session_id`。
3. 调用 `handle_explicit_memory_message(msg, store, session_id=session_id)`。
4. 若 `result.handled=True`：
   - 记录日志；
   - 使用 `Sender.send(msg, decision, result.reply, actual_tier="local")` 回复；
   - 立即 `return`；
   - 不执行 `builder.build_messages(...)`、`router.call(...)`、LLM 调用。
5. 若未命中：继续原 C3.1/C4/LLM 链路。

## Handler 行为

`src/plugins/yangyang/memory/explicit_handler.py`：

- 仅 owner 私聊生效。
- 非 owner：pass，不写入。
- 群聊：pass，不写主脑。
- 高置信 write：payload 清楚时直接调用 `MemoryStore.add_explicit_memory(...)` 写入长期记忆。
- 中置信 write：创建内存态 pending，等待确认/取消。
- pending 确认：写入 `source=explicit_confirmed`，清 pending。
- pending 取消：不写入，清 pending。
- 无 pending 时 `确认/好/是/取消` 等确认/取消词不会被拦截。
- query/audit/none：只读或普通聊天，pass，不写入。
- pending 为进程内内存态，默认 TTL 300 秒；重启丢失可接受。

`MemoryStore.add_explicit_memory(...)` 写入字段要点：

- `scope=private_user`
- `kind=technical_note`
- `slot=explicit_note`
- `source=owner_command` 或 `explicit_confirmed`
- `tags` 包含 `explicit / owner_command / private / manual_note`
- `payload/value/evidence` 保留显式命令及证据文本

## 本包不实现

- 群聊显式记忆 / 群友黑料库。
- 亲密日志 / intimacy detail / intimacy summary。
- cron / Ops。
- 主动陪伴、open_loop、Phase D。
- MiniMax 真实调用。
- 群聊主动发言或群聊长期记忆注入扩大。

## 测试结果

在开发仓库执行：

```bash
python3 -m py_compile \
  src/plugins/yangyang/__init__.py \
  src/plugins/yangyang/memory/explicit_handler.py \
  src/plugins/yangyang/memory/explicit_memory.py \
  src/plugins/yangyang/memory/store.py \
  tests/test_explicit_memory.py \
  tests/test_memory_phase_c.py \
  tests/test_provider.py
```

结果：通过，无语法错误。

```bash
python3 -m pytest -q tests/test_memory_phase_c.py tests/test_provider.py tests/test_explicit_memory.py
```

结果：`67 passed in 0.64s`。

## 覆盖方式

本包带顶层目录 `yangyang_m2_1_explicit_memory_handler_20260604/`，覆盖到目标仓库时使用：

```bash
tar -xzf dist/patches/yangyang_m2_1_explicit_memory_handler_20260604.tar.gz \
  -C /path/to/yangyang_nonebot_mvp \
  --strip-components=1
```

## runtime_config

本包不包含、不覆盖 `runtime_config.json`，也不修改运行时配置。

## 真机验收步骤

1. owner 私聊发送：`记一下：M2.1 handler 测试条目`。
2. 检查 `long_term/memories.jsonl` 或对应 store 是否新增 explicit/source/payload/evidence。
3. owner 私聊发送：`你记得我昨天说了什么吗`，确认不新增 explicit memory。
4. owner 私聊发送：`刚才那个也记一下`，出现 pending 确认；再发送 `确认`，确认写入。
5. 无 pending 时发送 `确认` / `好` / `是`，确认不被 M2.1 handler 拦截，继续普通链路。
6. 群聊发送：`记一下xxx`，确认不写主脑长期记忆。
7. C3.1 回归：`我晚上喜欢打什么游戏` 仍命中结构化记忆查询。

## 禁区确认

本包未触碰：

- 群聊闸门、owner gate、loop guard、kill switch。
- 群聊注入扩大、群聊主动开关。
- C1 被动写入语义。
- 真实数据文件。
- runtime_config。
- MiniMax 真实调用。
- cron / Ops。
- 主动陪伴、open_loop、Phase D。
- 宿主机生产服务或重启流程。
