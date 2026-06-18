# C3.1 Structured Memory Query Router v1（2026-06-04）

基于当前稳定基线：`yangyang_c4_subject_guard_on_m1_20260604.tar.gz`

基线 SHA256：`c2590ca16f2ee0103e65b8c05d62f0af65b3cc74490341367be4836fd0d0e68a`

## 目标

强化长期记忆的“怎么想起来”：当用户显式询问自己的偏好/习惯/信息时，优先按结构化 slot 查询长期记忆；未命中则回退 C4 原有 scope + 关键词/权重检索。

本补丁只做查询路由，不扩展写入类型，不做主动陪伴、不做群聊主动、不做 Phase D。

## 实现摘要

新增 `src/plugins/yangyang/memory/query_router.py`：

- 定义 `StructuredMemoryQuery(intent, kind, slots, confidence, reason, question_text)`。
- 实现 `detect_structured_memory_query(text)`。
- 识别条件：
  - 有疑问特征：`什么/啥/哪个/哪款/哪种/吗/么/？/?`。
  - 指向用户自己：`我/我的/自己/之前说过/你记得我` 等。
  - 有偏好/习惯/记忆读取意图：`喜欢/最喜欢/平时/通常/一般/晚上/你记得` 等。

接入 `MemoryRetriever.retrieve()`：

- 在现有 scope 过滤之后检测结构化问句。
- 命中结构化 query 时，先按 `kind + slot` 精准筛选 active long-term entries。
- 结构化命中项以高优先级排在结果最前。
- 结构化未命中时，完全回退原 C4 评分/排序行为。
- 不绕过 private/group scope 隔离。
- C4 Subject Guard 的 rendered memory section 保持不变。

接入 prompt 链路：

- `PromptBuilder.build_messages()` 将当前用户消息文本传给 `MemoryStore.build_memory_prompt(..., query=...)`。
- `MemoryStore.build_memory_prompt()` 将 query 传给 `MemoryRetriever.retrieve()`。
- 旧调用保持兼容：`query` 是末尾可选参数，默认空字符串。

## 支持的 query -> slot 映射

第一版规则：

- `打/玩` 或包含 `游戏` -> `favorite_game`
  - 例：`我晚上喜欢打什么游戏`
  - 例：`我最喜欢打什么`
  - 例：`我最喜欢什么游戏`
  - 例：`我喜欢玩什么游戏`
- `喝/饮料/奶茶/咖啡/可乐/果汁/茶` -> `favorite_drink`，并兼容 fallback 到 `favorite_food`
  - 说明：当前写入侧历史规则曾把“喝/脉动/饮料”归入 `favorite_food`，因此读取侧主 slot 是 `favorite_drink`，同时带 `favorite_food` alias，避免旧记忆查不到。
- `吃/食物/菜/饭/零食/甜品` -> `favorite_food`
- `听/音乐/歌/歌曲` -> `leisure_activity`，并兼容 `favorite_music`
  - 说明：当前 `CandidateExtractor` 对“听歌/听音乐”写入 `leisure_activity`。
- `看/追/刷` -> `leisure_activity`

## 行为约束

- 显式问句只用于读取/检索，不写入 C1/C2。
- C1 问句防线继续保留：包含疑问 marker 的消息不会生成 preference/habit write candidates。
- Subject Guard 继续保留在 `[来自长期记忆的事实]` section 中。
- 未命中结构化 slot 时不报错，回退原 C4 检索。
- 不修改真实数据文件，不修改 runtime_config。
- 不改群聊闸门、owner gate、loop guard、kill switch。
- 不扩大群聊注入，不开启群聊主动。
- 不接 MiniMax 真实调用。

## 测试结果

已执行：

```bash
python3 -m py_compile \
  src/plugins/yangyang/memory/query_router.py \
  src/plugins/yangyang/memory/retrieval.py \
  src/plugins/yangyang/memory/store.py \
  src/plugins/yangyang/core/prompt_builder.py \
  src/plugins/yangyang/memory/__init__.py \
  tests/test_memory_phase_c.py \
  tests/test_provider.py

python3 -m pytest -q tests/test_memory_phase_c.py tests/test_provider.py
```

结果：`51 passed in 0.57s`

新增/覆盖重点：

1. `我晚上喜欢打什么游戏` -> `favorite_game`。
2. `我喜欢喝什么` -> `favorite_drink`，并兼容 `favorite_food` alias。
3. 长期记忆同时存在 `favorite_game=打绝区零` 与 `favorite_drink=脉动` 时，问 `我晚上喜欢打什么游戏`，rendered prompt 中 `打绝区零` 排在 `脉动` 前。
4. 结构化 slot 未命中时回退原 C4 检索，不崩。
5. C1 问句防线继续通过：问句不产生 write candidates。
6. rendered memory section 中仍包含 Subject Guard。

## 覆盖方式

补丁包带顶层目录：`yangyang_c3_1_structured_memory_query_router_20260604/`

覆盖到仓库根目录时使用：

```bash
tar -xzf dist/patches/yangyang_c3_1_structured_memory_query_router_20260604.tar.gz \
  -C /AstrBot/data/workspaces/default_FriendMessage_335059272/yangyang_nonebot_mvp \
  --strip-components=1
```

覆盖后建议执行：

```bash
python3 -m py_compile \
  src/plugins/yangyang/memory/query_router.py \
  src/plugins/yangyang/memory/retrieval.py \
  src/plugins/yangyang/memory/store.py \
  src/plugins/yangyang/core/prompt_builder.py \
  src/plugins/yangyang/memory/__init__.py \
  tests/test_memory_phase_c.py \
  tests/test_provider.py
python3 -m pytest -q tests/test_memory_phase_c.py tests/test_provider.py
```
