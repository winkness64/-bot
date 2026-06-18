# Phase 6C Owner Command Tighten Patch

## 修复点
- 收紧 owner_command / explicit_command 判定，不再因普通聊天中包含“回复/不回复/回应”等词自动命中。
- 仅以下场景触发明确指令：
  - 明确 @bot
  - 明确命令前缀：`/yy`、`/yy-smoke-current`、`秧秧smoke`、`/秧秧`、`!yy`
  - 文本以 bot 名/别名开头，并紧跟明确命令动词，例如：`秧秧 回应小维`、`秧秧 帮我回复小维`、`小云雀 总结一下`
  - owner_action_router 能解析出结构化 owner action，且动作/目标足够明确
- owner_action_router 增加显式信号门槛，避免纯关键词普通聊天被解析为 owner action。
- 保持 @bot 自动回复链路、owner 明确命令优先权、current-session smoke 手动链路不变。

## 影响文件
- `src/plugins/yangyang/core/owner_rules.py`
- `src/plugins/yangyang/core/event_adapter.py`
- `src/plugins/yangyang/core/owner_action_router.py`
- `src/plugins/yangyang/__init__.py`
- `tests/test_phase6c_owner_command_tighten.py`
- `tests/mock_pipeline_test.py`
- `tests/test_current_session_sandbox_e2e.py`

## 应用步骤
1. 解压补丁包到项目根目录。
2. 按 `MANIFEST_phase6c_owner_command_tighten.txt` 校对文件列表。
3. 校验 `SHA256SUMS.txt`。
4. 运行以下命令复测：
   - `python3 tests/test_phase6c_owner_command_tighten.py`
   - `python3 tests/test_phase6a_atbot_decision_trace.py`
   - `python3 tests/mock_pipeline_test.py`
   - `python3 scripts/check_project.py`

## 复测重点
### 必须不触发
- `你怎么不回复捏啊233`
- `怎么没人回复我`
- `这句话不用回复`
- `回复这个词只是普通聊天`
- `回应一下也只是说说`

### 必须触发
- `@bot 你好`
- `/yy-smoke-current 回应小维`
- `秧秧smoke 回应小维`
- `秧秧 回应小维`
- `秧秧 帮我回复小维`
- `/yy 回应小维`

## 回滚说明
若需回滚，只恢复上述影响文件到补丁前版本即可。
