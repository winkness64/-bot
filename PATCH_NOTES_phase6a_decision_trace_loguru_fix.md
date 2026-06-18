# Phase 6A Decision Trace Loguru Format Fix

## 范围
本补丁仅修复 `decision_trace` 观测日志的渲染格式。

## 背景
Phase 6A dry-run 已确认决策链路和发送 dry_run 均会触发，但新增的 `decision_trace` 日志采用了旧式 `%s` 占位写法。在 NoneBot/Loguru 环境下，这类占位不会按预期展开，导致关键观测字段无法直接读到实际值。

## 修改内容
- 将 `src/plugins/yangyang/__init__.py` 中 `decision_trace` 日志模板从 `%s` 改为 Loguru `{}` 风格。
- 保持原有字段、顺序与逻辑不变：
  - `uid`
  - `group_id`
  - `channel`
  - `bot_self_id`
  - `text`
  - `at_user_ids`
  - `is_at_bot`
  - `is_owner`
  - `owner_command`
  - `explicit_command`
  - `should_reply`
  - `reason`
  - `is_forced`
  - `model_tier`
- 新增静态测试，防止 `decision_trace` 再次回退到 `%s` 占位格式。

## 非目标
- 不修改决策逻辑
- 不修改发送闸门
- 不修改 dry-run 行为
- 不修改 runtime config
- 不启动 bot，不发送消息

## 验证
执行：
- `python3 tests/test_phase6a_atbot_decision_trace.py`
- `python3 scripts/check_project.py`

若通过，则说明本次仅为日志渲染修复。