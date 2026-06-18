# Current-Session Manual Smoke 调用示例

部署总清单见：`deploy/host_deploy_checklist.md`

## 定位

`manual smoke` 是 **仅当前会话** 的小范围实测入口。

它的目标不是开放生产发送，也不是开放跨群能力，而是让 owner 在明确、可回滚、可审计的前提下，对 `reply_current -> current_session` 这条链路做一次受控试发。

保守边界：
- 默认关闭
- 只允许 owner
- 只允许当前会话 `reply_current/current_session`
- 必须显式开启 `explicit_enable=True`
- 仍统一经过 delivery integration / sender factory / safety / audit
- **跨群 `send_group_message` 继续锁死**
- **普通 owner action 不自动真发**，只有带前缀 trigger 命令才会进入 manual smoke

## 本轮显式 Trigger 命令

真实 smoke 不要直接发：
- `回应小维`

而是发：
- `/yy-smoke-current 回应小维`
- `/秧秧smoke 回应小维`

说明：
- 支持前缀后普通空格或全角空格
- 前缀后必须带非空 inner text
- inner text 会被当作 owner action 文本重新解析
- 只有当 inner text 解析成 `reply_current/current_session` 时，才允许进入 manual smoke
- 若 inner text 解析成 `send_group_message` / `group`，仍会 `cross_session_blocked`

## 最小调用示例

在 NoneBot 事件处理中，只能放在**手动 smoke 分支**里显式调用：

```python
result = await run_current_session_manual_smoke_if_enabled(
    msg=msg,
    config=config,
    bot=bot,
    event=event,
    explicit_enable=True,
    dry_run=False,
)
```

说明：
- `msg`：当前会话里已完成 owner action 解析、gate、plan、draft 挂载的内部消息对象
- `config`：运行时配置
- `bot` / `event`：当前 NoneBot 会话对象，供 current-session sender 使用
- `explicit_enable=True`：**只能出现在手动 smoke 分支**
- `dry_run=False`：表示本次允许进入真实试发链路；若传 `True`，则不会真实发送

## 严禁全局默认开启 explicit_enable

`explicit_enable=True` 只能放在人工手动 smoke 的受控代码分支里，不能：
- 作为全局默认值
- 直接写进普通聊天主流程
- 让所有 owner 指令自动带上
- 用来接管生产投递

错误示例：

```python
# 不允许：普通主流程默认开启
result = await run_current_session_manual_smoke_if_enabled(
    msg=msg,
    config=config,
    bot=bot,
    event=event,
    explicit_enable=True,
)
```

正确思路：
- 普通主流程保持关闭
- 只有你明确进入“手动 smoke 测试入口”时，才传 `explicit_enable=True`

## 必须满足的配置全开条件

manual smoke 想真正进入当前会话试发，以下配置必须同时为 `true`：

- `owner_action_manual_smoke_enabled=true`
- `owner_action_nonebot_sender_enabled=true`
- `owner_action_execution_enabled=true`
- `owner_action_allow_reply_current=true`
- `owner_action_current_session_delivery_enabled=true`

建议先做 NapCat config check + runtime wiring check，再做配置 enable、ready check、rehearsal，最后才去真实 NoneBot/OneBot runtime 里做 smoke。真实 smoke 必须等 NoneBot runtime 与 OneBot 已连接后再做。

补丁说明：当前会话 smoke trigger 命中前缀后，现在会先 `cfg.reload()` 重新读取磁盘 `runtime_config.json`。也就是说，**代码补丁加载生效后**，再执行 `toggle_current_session_smoke.py --enable/--disable` 不需要重启 NoneBot 就能让 smoke gate 读取到最新开关状态；但**本次代码补丁本身**仍需要先重启一次 NoneBot 进程，让新代码加载进去。测试完成后仍建议立即 disable，回到安全态。

```bash
python3 scripts/check_napcat_onebot_config.py
python3 scripts/check_nonebot_runtime_ready.py
python3 scripts/toggle_current_session_smoke.py --show
python3 scripts/toggle_current_session_smoke.py --enable --dry-run
python3 scripts/toggle_current_session_smoke.py --enable --yes
python3 scripts/check_current_session_smoke_ready.py
python3 scripts/run_current_session_smoke_rehearsal.py
python3 scripts/run_current_session_smoke_rehearsal.py --mock-send
```

补充说明：
- `check_napcat_onebot_config.py` 先只读检查 `.env` / `.env.example` / `bot.py` / `pyproject.toml` 的 NapCat + OneBot v11 接线准备。
- `check_nonebot_runtime_ready.py` 再只读检查启动入口、依赖、插件加载、OneBot driver 提示、hook 接线与安全态。
- 它不会启动 bot，不会连接 OneBot，不会发送消息，也不会修改配置。
- 当前 AstrBot/API 窗口**不是** `yangyang_nonebot_mvp` 的真实 NoneBot runtime，不能替代真实 `bot/event` 去做 smoke。

## 允许范围

当前仅允许：
- owner
- `reply_current`
- `current_session`

也就是说，只能把内容发回**当前这次会话**。

以下情况仍会被拦截：
- 非 owner
- 缺少 `owner_action`
- 缺少 reply draft / execution plan
- `action_type != reply_current`
- `destination_type != current_session`
- 缺少当前 `bot` / `event`
- 任一关键开关未打开

## dry_run 语义

`dry_run=True` 时：
- 不真实发送
- 不登记 dedup key
- 仍可走安全判定和审计观察
- rehearsal runner 默认就是这个模式

这意味着：
- 先做一次 dry_run，不会污染后续真实试发
- 之后第一次 `dry_run=False` 的真实试发仍可通过
- `python3 scripts/run_current_session_smoke_rehearsal.py --mock-send` 虽然走非 dry-run 路径，但也只是 mock `bot.send`，不是真实 QQ 发送

## 跨群仍锁死

即使 manual smoke 开启，本轮依然：
- 不开放 `send_group_message`
- 不开放 `destination_type=group`
- 不开放跨群 / 跨会话主动发送

命中这类路径时，应看到类似：
- `cross_session_blocked`
- `send_group_locked`

## 审计与排查

推荐 smoke 前先开一个只读观察终端：

```bash
python3 scripts/inspect_owner_action_audit.py --tail-follow
```

然后另开一个终端做 ready check / rehearsal / 手动触发，这样试发时能实时看到新增 audit。

推荐真实 smoke 前先做本地彩排：

```bash
python3 scripts/run_current_session_smoke_rehearsal.py
python3 scripts/run_current_session_smoke_rehearsal.py --mock-send
```

说明：
- rehearsal runner 只用 mock bot / mock event，不连接 QQ / OneBot。
- 默认命令是 `/yy-smoke-current 回应小维`。
- `--mock-send` 也只是 mock `bot.send`，不是向真实 QQ 发消息。

推荐触发话术：
- `/yy-smoke-current 回应小维`
- `/秧秧smoke 回应小维`

强调：
- 不要直接发 `回应小维` 期待真实 smoke
- 普通 owner action 仍只走普通解析/草稿链路，不自动真发

试发后可查看 audit JSONL：

```bash
python3 scripts/inspect_owner_action_audit.py --limit 20
python3 scripts/inspect_owner_action_audit.py --real-send-only
python3 scripts/inspect_owner_action_audit.py --duplicates-only
python3 scripts/inspect_owner_action_audit.py --tail-follow
python3 scripts/inspect_owner_action_audit.py --tail-follow --real-send-only
python3 scripts/inspect_owner_action_audit.py --tail-follow --duplicates-only
```

重点观察字段：
- `real_send`
- `duplicate`
- `reason`
- `content_preview`
- `action_type`
- `destination`

试发后建议重点确认：
- `real_send=true/false` 是否符合预期
- 是否出现 `duplicate=true` 或 `duplicate_blocked`
- `reason` 是否为 `sent`、`dry_run_no_delivery`、`cross_session_blocked` 等预期值

强调：
- 该 audit 查看工具只读
- 不连接 QQ / OneBot
- 不发送消息
- 不开放跨群

## 回滚方式

出现任何风险时，直接关闭以下任一开关并重启：

- `owner_action_manual_smoke_enabled=false`
- 或 `owner_action_nonebot_sender_enabled=false`
- 或 `owner_action_current_session_delivery_enabled=false`

推荐最小回滚：
- 直接执行 `python3 scripts/toggle_current_session_smoke.py --disable --yes`
- 如需回到旧配置，再执行 `python3 scripts/toggle_current_session_smoke.py --restore backups/runtime_config/xxx.json --yes`
- 若只是切换 enable/disable，补丁后无需为 smoke gate 再重启 NoneBot；但若替换了本补丁代码文件本身，仍需先重启一次 NoneBot 让新代码加载
- 然后按需重启

这样会立刻关闭当前会话手动 smoke 入口，而不会影响其它默认关闭边界。
