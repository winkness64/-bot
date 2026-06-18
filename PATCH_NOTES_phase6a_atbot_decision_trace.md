# Phase 6A @bot Decision Trace Patch

## 修复点
- 在 `src/plugins/yangyang/__init__.py` 增加轻量 `decision_trace` 日志。
- 日志仅在以下任一条件满足时打印，避免普通群聊刷屏：
  - `msg.is_owner == True`
  - `msg.is_at_bot == True`
  - `msg.at_user_ids` 非空
  - `decision.should_reply == True`
- 在 `src/plugins/yangyang/core/event_adapter.py` 为 `_extract_at` 和 `_extract_at_user_ids` 增加 `raw_message` CQ 兜底解析：即使 `event.message` 没有 `at segment`，只要 `raw_message` 含 `[CQ:at,qq=...]`，也能识别。
- `qq=all` 不当作指定用户，也不会进入 `at_user_ids`。
- 新增独立测试 `tests/test_phase6a_atbot_decision_trace.py`，无需启动 NoneBot。

## decision_trace 日志字段
日志名：`yangyang plugin: decision_trace ...`

字段包含：
- `uid, group_id, channel, bot_self_id, text`
- `at_user_ids`
- `is_at_bot, is_owner, owner_command, explicit_command`
- `should_reply, reason, is_forced, model_tier`

## 如何解读 Phase 6A 复测日志
在测试群 `622162372` 用 owner `335059272` 执行：
- `@3940223711 你好`

若看到：
- `at_user_ids` **不包含** `bot_self_id=3940223711`
  - 说明大概率是 **@错账号**，不是决策链路问题。
- `at_user_ids` **包含** `3940223711`，但 `is_at_bot=false`
  - 才说明是 **@ 解析问题**，需要继续查适配层。
- `is_at_bot=true` 且 `decision.should_reply=true reason=at_bot`
  - 说明 decision 已放行，后续应继续进入 `model_router dry_run` 和 `sender dry_run`。
- `is_owner=true` 但 `is_at_bot=false` 且 `explicit_command=false` 且 `should_reply=false reason=default_silent`
  - 说明当前消息只是 owner 普通文本，按设计静默。

## 应用步骤
1. 解压补丁包到项目根目录。
2. 核对补丁文件覆盖到：
   - `src/plugins/yangyang/__init__.py`
   - `src/plugins/yangyang/core/event_adapter.py`
   - `tests/test_phase6a_atbot_decision_trace.py`
   - `PATCH_NOTES_phase6a_atbot_decision_trace.md`
3. 按下方命令执行复测。

## 复测命令
```bash
python3 tests/test_phase6a_atbot_decision_trace.py
python3 tests/mock_pipeline_test.py
python3 scripts/check_project.py
```

## 线上验证建议
仅在现有 dry-run 条件下验证，不改 runtime config、不启 real send：
1. owner 账号 `335059272` 在测试群 `622162372` 发送 `@3940223711 你好`
2. 查看 NoneBot 日志是否出现：
   - `yangyang plugin: decision_trace ...`
   - `model_router ... dry_run`
   - `sender ... dry_run`

## 变更范围
本补丁只做最小侵入修复与排障日志，不改 runtime config，不改 dry-run 逻辑，不启动 bot，不连接外部服务。
