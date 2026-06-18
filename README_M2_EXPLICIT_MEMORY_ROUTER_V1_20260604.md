# M2 Explicit Memory Router v1 · 2026-06-04

基于 `Memory M1 C3.1 Stable`：

- stable 包：`dist/patches/yangyang_memory_m1_c3_1_stable_20260604.tar.gz`
- SHA256：`81613bdc418224ceba56db3f9878a1d101efa57015738a52ca1393720fe9a49d`

## 本包目标

实现显式记忆意图路由第一版，解决“不能见到‘记’字就写入”的问题。

分类结果：

- `write`：显式写入，例如 `记一下：以后迁移包只发私聊`。
- `query`：记忆查询，例如 `你记得我昨天说了什么吗`。
- `audit`：记忆审计，例如 `你在记录啥`。
- `confirm` / `cancel`：二次确认词。
- `none`：普通聊天。

## 行为原则

- 高置信显式写入 + payload 清楚：可直接写入。
- 中置信/上下文依赖：进入二次确认兜底。
- 疑问句默认读/审计，不写入。
- v1 优先 owner 私聊显式记忆；群聊群记忆后续单独做。

## 实现内容

新增：

- `src/plugins/yangyang/memory/explicit_memory.py`
  - `ExplicitMemoryIntent`
  - `detect_explicit_memory_intent(text)`

扩展：

- `MemoryStore.add_explicit_memory(...)`
  - 以 `kind=technical_note` / `slot=explicit_note` 保存。
  - 标记 `source=owner_command` 或 `explicit_confirmed`。
  - tags 包含 `explicit / owner_command / private / manual_note`。

测试：

- `tests/test_explicit_memory.py`

## v1 接入状态

本包实现 intent router + store method + tests。

真实 NoneBot handler 接入建议下一步单独做：

1. owner 私聊收到消息。
2. 调用 `detect_explicit_memory_intent(text)`。
3. `write/high` 且 `should_write=True`：调用 `store.add_explicit_memory(...)`。
4. `write/medium`：创建 pending confirmation，等待 `confirm/cancel`。
5. `query/audit`：不写入，转 C3.1/C4 或审计视图。

## 后续预留

### 亲密互动双层日志

未来 `记录这次亲密互动` 应分流到：

- `intimacy_detail`：从 chat_history DB 读取窗口，生成详细日志，高敏 owner-only，默认不自动注入。
- `intimacy_summary`：生成 agent 可用摘要，private-owner-only。

不靠模型当前上下文硬撑。

### 群聊群记忆 / 群友黑料库

未来群聊 `记一下红尘是哈基GAY` 只写当前 group scoped `group_meme`，不写主脑：

- `literal_fact=false`
- `usage_policy=group_roast_only`
- 主脑可按权限查询，但不自动吸收成私聊记忆。

## 覆盖方式

包带顶层目录：

```bash
tar -xzf dist/patches/yangyang_m2_explicit_memory_router_v1_20260604.tar.gz \
  -C /path/to/yangyang_nonebot_mvp \
  --strip-components=1
```

## 禁区

本包未触碰：

- 群聊闸门 / owner gate / loop guard / kill switch
- 群聊注入 / 群聊主动
- C1 被动写入语义
- 真实数据文件
- runtime_config
- MiniMax 真实调用
- cron / Ops
- 主动陪伴 / open_loop / Phase D
- 宿主机生产服务
