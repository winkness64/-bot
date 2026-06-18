# Current Session Smoke Runtime Reload Patch

## 修复点

本补丁修复 Phase 3A 初测里的两个不稳点：

1. `toggle_current_session_smoke.py --enable/--disable` 只改磁盘 `src/plugins/yangyang/data/runtime_config.json`，但运行中插件全局 `cfg` 不自动 reload，导致 smoke gate 不能立即读到新值。
2. `/yy-smoke-current ...` 触发链路可能被普通 `decision.should_reply == False` 默认静默逻辑提前 return，导致显式 smoke prefix 不稳。

补丁后的行为：
- 在 `src/plugins/yangyang/__init__.py` 收到消息后，先尽早解析 `parse_current_session_smoke_trigger_command(...)`。
- 若命中 smoke prefix，则先执行 `cfg.reload()`，再继续 current-session smoke gate。
- 记录日志：
  - `yangyang plugin: current-session smoke trigger matched uid=... channel=... reload_status=... enabled=... dry_run=...`
- smoke prefix 命中后，会优先走 `handle_current_session_smoke_trigger_if_matched(...)`。
- smoke prefix 命中后，不再被普通 `decision.should_reply == False` 默认静默提前吞掉。
- 安全边界保持不变：
  - 非 owner 仍 `not_owner`
  - `owner_action_manual_smoke_enabled=false` 仍阻断
  - dry_run 不真实发送
  - `send_group_message` / 跨群路径仍 `cross_session_blocked`
  - 未开放跨群真实发送

## 覆盖方法

本补丁新增/更新覆盖点：

- `tests/test_current_session_runtime_reload_patch.py`
  - A. RuntimeConfig `reload()` 能读取磁盘 toggle 后新值
  - B. smoke prefix 即使处于 default silent，也会调用 smoke handler，不被提前 return
  - C. 非 owner 仍返回 `not_owner`
  - D. dry_run 仍返回 `dry_run_no_delivery`，`real_send=false`
  - E. `send_group_message` / `去群里...` 仍 `cross_session_blocked`
- 保留既有：
  - `tests/test_current_session_smoke_trigger.py`
  - `tests/test_current_session_manual_smoke.py`

## 娅娅笔记本应用步骤

```bash
cd /opt/yangyang_nonebot
tar -xzf yangyang_current_session_smoke_reload_patch_*.tar.gz -C /opt/yangyang_nonebot
.venv/bin/python tests/test_current_session_runtime_reload_patch.py
.venv/bin/python scripts/check_current_session_smoke_ready.py
# 重启 NoneBot 进程，使代码补丁生效
# 前台运行则 Ctrl+C 后重新 .venv/bin/python bot.py
```

说明：代码补丁本身需要重启 NoneBot 使新代码加载；之后 toggle enable/disable 不再需要重启。

## 推荐 Phase 3A-bis 复测命令

```bash
cd /opt/yangyang_nonebot
.venv/bin/python tests/test_current_session_runtime_reload_patch.py
.venv/bin/python tests/test_current_session_smoke_trigger.py
.venv/bin/python tests/test_current_session_manual_smoke.py
.venv/bin/python scripts/check_current_session_smoke_ready.py
.venv/bin/python scripts/check_project.py
.venv/bin/python scripts/toggle_current_session_smoke.py --show
.venv/bin/python scripts/toggle_current_session_smoke.py --enable --yes
.venv/bin/python scripts/check_current_session_smoke_ready.py
# 确认 NoneBot 已用本补丁代码重启过一次
# QQ 当前测试会话发送：/yy-smoke-current 回应小维
.venv/bin/python scripts/toggle_current_session_smoke.py --disable --yes
```

## 回滚方式

最小回滚：

```bash
cd /opt/yangyang_nonebot
python3 scripts/toggle_current_session_smoke.py --disable --yes
```

如果要回退代码补丁本身：

1. 用你现有代码备份/版本管理恢复以下文件：
   - `src/plugins/yangyang/__init__.py`
   - `tests/test_current_session_runtime_reload_patch.py`
   - `docs/current_session_smoke_example.md`
   - `PROJECT_PROGRESS.md`
2. 恢复后重启 NoneBot。

如果要回退配置：

```bash
python3 scripts/toggle_current_session_smoke.py --restore backups/runtime_config/xxx.json --yes
```

## 安全提醒

- 本补丁没有打开跨群 `send_group_message`。
- 本补丁没有修改默认安全态为 enabled。
- 真实 smoke 完成后仍建议立即执行 disable。
- 不要在当前 AstrBot/API 窗口把 mock/单测结果误当成真实 NoneBot runtime 行为。
