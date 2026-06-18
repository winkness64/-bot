# yangyang_nonebot_mvp

秧秧 NoneBot 新内核 MVP 第一阶段，当前已补上 **独立启动脚手架**、**dry_run 联调模式**、**一键检查脚本** 与 **离线 mock 测试**。

## 首页安全声明

- 当前 AstrBot/API 聊天窗口**不能替代** NoneBot runtime 的真实 `bot/event`。
- `current-session smoke` 默认关闭。
- 普通 owner action 不自动真发；普通 `回应小维` **不会**触发真实 smoke。
- 跨群 `send_group_message` 仍锁死。

## README 首页三入口

### 1. 开发 / 单测 / mock rehearsal（当前容器可执行）

适用位置：**当前 AstrBot / Docker 开发容器**。

这里可以做：
- 跑测试
- 跑 `check_project`
- 跑 mock rehearsal
- 做只读检查与文档核对

这里**不会**：
- 连接真实 QQ / OneBot
- 替代真实 NoneBot runtime
- 提供真实 `bot/event`

推荐命令：

```bash
python3 scripts/check_project.py
python3 scripts/check_napcat_onebot_config.py
python3 scripts/run_current_session_smoke_rehearsal.py
python3 scripts/run_current_session_smoke_rehearsal.py --mock-send
```

### 2. 宿主机部署（真实运行环境）

适用位置：**宿主机 / 旧笔记本 Ubuntu 的项目目录**。

文档入口：
- `docs/host_nonebot_install.md`
- `deploy/host_deploy_checklist.md`
- `docs/napcat_onebot_setup.md`
- `deploy/napcat_reverse_ws_host_checklist.md`
- `docs/host_handoff_package.md`

#### 先生成交接包

如果需要把当前 MVP 项目通过宝塔下载到娅娅笔记本或其他宿主机，先看：`docs/host_handoff_package.md`

示例命令：

```bash
bash scripts/build_host_handoff_package.sh --dry-run
bash scripts/build_host_handoff_package.sh
```

推荐命令：

```bash
bash scripts/host_preflight_check.sh
bash scripts/host_setup_nonebot_env.sh --dry-run
bash scripts/host_setup_nonebot_env.sh
.venv/bin/python scripts/check_napcat_onebot_config.py
.venv/bin/python scripts/check_nonebot_runtime_ready.py
```

强调：**不要在当前 AstrBot / Docker 容器执行真实安装。**

如果宿主机是娅娅笔记本：仍建议不要默认长期 root 运行，并注意与 AstrBot 的端口、日志目录、数据目录冲突。

### 3. 真实 current-session smoke（必须等 NoneBot + OneBot 已连接）

前提必须同时满足：
- 宿主机 NoneBot 已启动
- OneBot / NapCat / Lagrange 已连接
- audit `tail-follow` 已开
- smoke toggle 已启用

文档入口：
- `docs/current_session_smoke_example.md`

推荐命令：

```bash
.venv/bin/python scripts/toggle_current_session_smoke.py --enable --yes
.venv/bin/python scripts/check_current_session_smoke_ready.py
.venv/bin/python scripts/run_current_session_smoke_rehearsal.py --mock-send
.venv/bin/python scripts/inspect_owner_action_audit.py --tail-follow
```

QQ 当前测试会话命令：

```text
/yy-smoke-current 回应小维
```

注意：
- 普通 `回应小维` 不会触发真实 smoke。
- 测试完成后立即执行 disable。
- 详情见 `docs/current_session_smoke_example.md`。

## 当前能力

- OneBot v11 群聊/私聊事件适配
- SQLite 消息入库与最近上下文读取
- RuntimeConfig JSON 原子保存与热配置接口
- 离线 mock 测试与 OwnerAction 端到端 dry_run 场景测试
- owner 配置支持：
  - `owner_uid` 旧字段兼容
  - `owner_uids` 新字段，默认包含 `335059272`
- OwnerAction Router MVP：
  - 仅解析 owner 指令，不执行
  - 输出 `OwnerAction` 轻量结构
  - 当前支持 `reply_current` / `send_group_message` / `silence_topic` / `cancel_reply` / `unknown`
  - owner 明确风格指令若缺少显式 action（如 `补刀/锐评/纠错/更正/评价/劝和`），MVP 默认回落到 `reply_current`
  - 可解析 `mediate` / `roast` / `correct` / `comment` / `normal` style
  - `send_group_message` 支持最小 `target_group_id` 解析：
    - 显式纯数字群号优先
    - 群聊命中“去群里/群里说”时优先取当前群 `group_id`
    - owner 私聊未写群号时可回退 `default_group_id` / `primary_group_id`
    - 无法解析时保持 `target_group_id=None` 并标记 `no_target_group`
  - 新增最小 `target_user_id` 解析：
    - owner 文本显式 QQ 号优先
    - 命中 `member_aliases` 时可解析常用群友，如 `小维/红尘/娅娅`
    - 存在真实 `@` 用户列表时，优先取非 bot 自己的被 `@` 用户
    - 若都无法解析，则保持 `target_user_id=None`，避免误判
  - 已接入主 pipeline 的安全观察位：
    - `msg.owner_action` 现已安全注入 PromptBuilder context
    - 仅在 `msg.is_owner` 且 `msg.owner_action` 存在时追加轻量结构化提示
    - 注入字段仅保留 `action_type/style/target_group/target_user/reason/raw_hint` 的短摘要
    - `raw_text` 不整段注入，默认短截断，防止 prompt 污染
    - `dry_run` 下会把结构化 action 摘要附加到模拟回复 / debug 输出
    - 示例：`[dry_run][owner_action] action=send_group_message style=mediate target_group=... target_user=... ...`
    - 仅可见，不真实跨会话发送
  - 非 `dry_run` 下仅解析并挂载上下文 / 记日志，不接执行层
  - OwnerAction execution gate MVP：
    - 新增执行权限配置总闸与分权限开关：`owner_action_execution_enabled`、`owner_action_allow_send_group_message`、`owner_action_allow_reply_current`、`owner_action_allow_internal_control`
    - 默认全部关闭；当前仅用于 gate / plan 可见性，不开放真实执行
    - `msg.owner_action` 存在时会继续计算 `msg.owner_action_gate`
    - `dry_run` 下会追加 gate 摘要，例如：`[dry_run][owner_action_gate] mode=dry_run allowed=true reason=...execution_disabled safe=false execution_enabled=false blocked_by_config=true`
    - 即便手工打开配置，本轮 executor 仍只生成计划，`real_send` 仍恒为 `False`
- OwnerAction Context Resolver MVP：
  - 新增 `src/plugins/yangyang/core/owner_action_context_resolver.py`
  - 仅解析 owner 指令所针对的群聊上下文，不真实执行
  - 支持 `quote` / `recent_by_user` / `recent_current_session` / `none` 四类来源
  - 数据仅来自当前 pipeline recent messages / memory store / mock 注入数据
  - `msg.owner_action_context` 已挂载到主 pipeline
  - `dry_run` 下新增摘要：`[dry_run][owner_action_context] ...`
  - PromptBuilder 现会在 owner 且存在 context 时追加短结构化上下文；缺上下文时提示“上下文不足，谨慎回应”
  - 真实执行层仍未开放，`execution_plan.real_send` 仍恒为 `False`
- OwnerAction Current-Session Delivery MVP：
  - 新增 `src/plugins/yangyang/core/owner_action_delivery.py`
  - 只允许受控 `reply_current -> current_session` 投递判定链路
  - 默认关闭，新增配置：`owner_action_current_session_delivery_enabled`
  - 即便已有 draft，未显式打开执行总闸 / reply_current 权限 / 当前会话投递开关时，仍不会真实投递
  - `send_group_message` / 跨群 destination 继续绝对锁死，reason 带 `cross_session_blocked` / `send_group_locked`
  - `internal_control` 本轮仅返回 blocked / not_implemented
  - 未注入 sender 时一律 `blocked/no_sender`
  - dry_run 下仅输出 delivery 摘要：`[dry_run][owner_action_delivery] ...`，不会真实发送
  - 真实生产投递仍需显式配置 + 明确 sender 注入；当前默认生产路径仍不会触发真实 owner action 投递
- OwnerAction E2E dry_run 场景测试：
  - 新增 `tests/test_owner_action_e2e_dryrun.py`
  - 覆盖 owner 指令完整链路：router / prompt context / gate / execution plan
  - 所有场景仅验证 dry_run 输出与消息挂载对象，不开放真实执行层
  - 当前真实执行层仍未开放，跨会话发送仍禁止
- 硬规则 DecisionEngine：
  - 私聊回复
  - owner/阿漂群聊 @bot：最高优先级放行
  - owner/阿漂明确命令白名单：最高优先级放行
  - 群聊明确 @ bot 回复
  - 群聊 quote/reply bot 时，仅引用不算回复资格，仍需同时 @bot
  - owner 明确指令不受普通 quote/reply 静默与普通 bot loop 误杀
  - 空消息/无效消息安全兜底不回复
  - 其它群聊默认静默
- CooldownManager：
  - 全局冷却
  - 同话题轮次冷却
  - 每日主动上限
  - bot loop 最近窗口判定后的群级冷却
- bot loop 增强配置：
  - `known_bot_uids`
  - `behavior.bot_loop_enabled`
  - `behavior.bot_loop_recent_limit`
  - `behavior.bot_loop_min_bot_messages`
  - `behavior.bot_loop_cooldown_seconds`
- PromptBuilder：
  - 注入公开记忆
  - 私聊注入私密记忆
  - 群聊 1-2 句约束
- ModelRouter：
  - OpenAI 兼容接口
  - V4 Flash / V4 Pro / GPT-5.5 tier 占位
  - 失败冷却与降级
  - dry_run 固定模拟回复
- Sender：
  - 后处理
  - 群聊/私聊发送
  - dry_run 下跳过真实发送
  - bot 回复入库
- Sender Adapter Interface MVP：
  - 新增 `src/plugins/yangyang/output/sender_adapter.py`
  - 默认 `NullSenderAdapter`，永远不发，返回安全 `SendResult`
  - 测试用 `FakeSenderAdapter`，只记录调用，不真实发送
  - 新增 `NoneBotCurrentSessionSenderAdapter`，仅支持当前会话 `reply_current`，内部仅走 `bot.send(event, content)`
  - 不实现 `send_group_message`，不接受外部 `group_id` 主动发群
  - `owner_action_delivery` 已统一走 adapter 风格接口
  - 真实 NoneBot sender 默认不注入、不启用，需显式注入且配置全开才可能生效
  - 跨群 / 跨会话发送仍锁死

## 本轮新增

- 新增独立 NoneBot 启动入口：`bot.py`
  - `nonebot.init()` 初始化
  - 注册 OneBot v11 adapter
  - 加载 `src/plugins` 下插件
  - 从项目根目录 `.env` 读取配置
- 补充 `.env.example`
  - 明确 OneBot 基础字段
  - 明确 `YANGYANG_DRY_RUN`
  - 明确 OpenAI / DeepSeek 兼容配置字段
- 补充 `pyproject.toml`
  - 明确 `nonebot2`
  - 明确 `nonebot-adapter-onebot`
  - 明确 `openai`
  - 增加 `python-dotenv` 以支持 `.env` 加载
- 更新联调说明
  - 安装依赖
  - 复制 `.env.example` 到 `.env`
  - dry_run 启动
  - 对接 OneBot
  - 测试群里 `@bot`

## 目录结构

```text
.
├── .env.example
├── .gitignore
├── PROJECT_PROGRESS.md
├── README.md
├── bot.py
├── pyproject.toml
├── scripts/
│   └── check_project.py
├── src/
│   └── plugins/
│       └── yangyang/
│           ├── __init__.py
│           ├── admin/
│           ├── core/
│           ├── data/
│           ├── memory/
│           ├── output/
│           └── tasks/
└── tests/
    └── mock_pipeline_test.py
```

## 三入口速查（首页收口）

README 首页统一分三条入口：
- 开发 / 单测 / mock rehearsal：当前容器内执行，不连接真实 QQ / OneBot，不代表真实 `bot/event`。
- 宿主机部署：只在宿主机 / 旧笔记本 Ubuntu 项目目录执行，见 `docs/host_nonebot_install.md`、`deploy/host_deploy_checklist.md` 与 `deploy/napcat_reverse_ws_host_checklist.md`。
- 真实 current-session smoke：必须等宿主机 NoneBot + OneBot 已连接后再做，见 `docs/current_session_smoke_example.md`。

### 开发入口补充

```bash
python3 tests/mock_pipeline_test.py
python3 tests/test_owner_action_e2e_dryrun.py
python3 scripts/check_project.py
```

### Host-side NoneBot Install

真实安装也建议在**宿主机 / 旧笔记本 Ubuntu 的项目根目录**内使用 `.venv`，不要在当前容器里直接安装运行依赖。

```bash
.venv/bin/python -m pip install -e ".[nonebot]"
```

上面的 `pip install -e` 命令应在**宿主机项目目录的 `.venv`** 中执行，不是在当前 AstrBot / Docker 开发环境里执行。

当前 Sender Adapter 说明：
- 默认仍是 `NullSenderAdapter`，不会真实发送 owner action。
- 已新增显式工厂入口：`src/plugins/yangyang/output/sender_adapter_factory.py`
- `NoneBotCurrentSessionSenderAdapter` 已加入，但默认不注入。
- 仅允许当前会话 `reply_current`。
- `send_group_message` / 跨群 / 跨会话继续锁死。
- 若后续要接真实发送，必须满足：非 dry_run + 显式注入 adapter + `owner_action_nonebot_sender_enabled=true` + `owner_action_execution_enabled=true` + `owner_action_allow_reply_current=true` + `owner_action_current_session_delivery_enabled=true`。

## 当前会话沙盒 E2E 验收

新增测试：`tests/test_current_session_sandbox_e2e.py`

覆盖范围：
- 默认配置下 owner 指令不会误发
- 配置全开且 `explicit_enable=True` 时，只允许当前会话 mock `bot.send(event, content)` 成功发送
- 同一条 owner 指令重复触发会被 dedup 拦截
- `dry_run=True` 不发送，且不污染 dedup，后续首次真实发送仍可通过
- `send_group_message` / 跨群路径继续锁死
- 普通群友同样话术不触发 owner action
- audit 使用临时 JSONL 文件，验证可解析与关键字段存在

运行：

```bash
python3 tests/test_current_session_sandbox_e2e.py
```

说明：
- 全程只用 mock bot / mock event / mock recent messages
- 不连接真实 QQ / OneBot
- 不开放跨群发送
- 默认真实 sender 仍关闭

## 当前会话投递安全层：防重复与审计日志

- 新增安全模块：`src/plugins/yangyang/core/owner_action_delivery_safety.py`
- 默认启用 safety：`owner_action_delivery_safety_enabled=true`，但**这不代表会真实发送**；真实 sender 仍需显式开关全开 + `explicit_enable=True`。
- 去重 TTL：`owner_action_delivery_dedup_ttl_seconds=300`，用于阻断同一 owner 指令在当前会话内的重复投递。
- dry_run 只做安全判定与审计，不登记去重 key，不影响后续非 dry_run 真发。
- 审计日志默认路径：`logs/owner_action_delivery_audit.jsonl`，配置项：`owner_action_delivery_audit_path`。
- 审计字段包含：time / action / destination / status / allowed / duplicate / attempted / delivered / real_send / reason / key / content_preview。
- 排障/回滚方式：
  - 临时关闭防重复：`owner_action_delivery_safety_enabled=false`
  - 临时关闭审计：`owner_action_delivery_audit_enabled=false`
  - 清空当前进程内去重状态：重启进程即可
- 仍然强调：`send_group_message` / 跨群发送继续锁死，不因 safety 层而开放。

## 当前会话真实投递集成入口

- 集成文件：`src/plugins/yangyang/output/current_session_delivery_integration.py`
- 默认关闭；主 pipeline 里默认 `explicit_enable=False`，不会自动接管 AstrBot/NoneBot 生产。
- 真实发送必须同时满足：配置全开 + `explicit_enable=True` + 提供当前 `bot` / `event`。
- 集成层内部固定走：`build_owner_action_sender_adapter(...) -> deliver_owner_action_reply_draft(...)`。
- `dry_run=true` 或调用时 `dry_run=True` 都不会发送。
- 只处理当前会话 `reply_current/current_session`。
- `send_group_message` / `destination_type=group` 仍锁死，不开放跨群发送。
- `internal_control` 仍是 `not_implemented`。
- 回滚方式仍是关闭 `owner_action_nonebot_sender_enabled` 或 `owner_action_current_session_delivery_enabled`。

## 如何开启当前会话真实投递 / 如何回滚

默认不开，也不会自动接管生产。

开启条件必须**同时满足**：
- `owner_action_nonebot_sender_enabled=true`
- `owner_action_execution_enabled=true`
- `owner_action_allow_reply_current=true`
- `owner_action_current_session_delivery_enabled=true`
- 集成侧显式传入当前 `bot` / `event`
- 调用 `build_owner_action_sender_adapter(config, bot=..., event=..., explicit_enable=True)`
- 且整体仍需处于 `dry_run=false`

保守规则：
- 任一开关未开，工厂都只返回 `NullSenderAdapter`
- 未显式 `explicit_enable=True`，工厂只返回 `NullSenderAdapter`
- 缺 `bot` 或 `event`，工厂只返回 `NullSenderAdapter`
- 工厂不接受 `target_group_id`，不创建跨群 sender，不实现 `send_group_message`
- 即便拿到真实当前会话 adapter，`send_group_message` / 跨群 destination 仍会被 delivery 层锁死

当前主 pipeline 仍保持默认回退 Null：
- 已预留显式注入点
- 但默认 `explicit_enable=False`
- 因此现有运行行为不变，不影响普通聊天/普通回复

回滚方式：
- 关闭 `owner_action_nonebot_sender_enabled`，或
- 关闭 `owner_action_current_session_delivery_enabled`
- 然后重启即可

## 当前会话手动 Smoke Test

默认关闭，且默认不接管生产。当前阶段只允许 **owner 在当前会话** 做受控真实试发，**绝不开放跨群 `send_group_message`**。

详细调用示例与边界说明见：
- `docs/current_session_smoke_example.md`

必须同时打开以下配置：
- `owner_action_manual_smoke_enabled=true`
- `owner_action_nonebot_sender_enabled=true`
- `owner_action_execution_enabled=true`
- `owner_action_allow_reply_current=true`
- `owner_action_current_session_delivery_enabled=true`

另外还必须满足：
- 调用手动 smoke 入口时显式传入当前 `bot` / `event`
- 调用时显式传 `explicit_enable=True`
- `explicit_enable=True` 只能放在手动 smoke 分支，不能全局默认开启
- 非 `dry_run`
- 仅 owner 可触发
- 仅允许 `reply_current/current_session`
- `dry_run` 不发送，且不登记 dedup

最小调用示例：

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

## Manual Smoke Trigger Hook

本轮新增的是 **owner-only、带前缀、仅当前会话** 的显式扳机。

不要直接发：
- `回应小维`

要发带前缀命令：
- `/yy-smoke-current 回应小维`
- `/秧秧smoke 回应小维`

规则：
- 只允许 owner
- 只允许 `reply_current/current_session`
- 普通 owner action **不会**自动真发
- `/yy-smoke-current 去群里劝和一下` 这类会解析成跨群路径，仍会被 `cross_session_blocked`
- 默认配置仍关闭；只有 toggle enable + ready check 通过后，且命中这个前缀分支时，内部才会显式传 `explicit_enable=True`
- trigger 层不直接 `bot.send`，最终仍统一走 manual smoke -> integration -> factory -> delivery -> safety -> audit
- 测完立刻 disable

推荐测试话术改为：
- owner 在**当前测试会话**发送：`/yy-smoke-current 回应小维`
- 或：`/秧秧smoke 回应小维`
- 不要直接发 `回应小维` 期待真实 smoke
- 不要测试跨群，不要测试 `去群里劝和一下`

完整流程：
1. `python3 scripts/toggle_current_session_smoke.py --enable --yes`
2. `python3 scripts/check_current_session_smoke_ready.py`
3. `python3 scripts/run_current_session_smoke_rehearsal.py --mock-send`
4. `python3 scripts/inspect_owner_action_audit.py --tail-follow`
5. 在当前会话发送带前缀命令
6. `python3 scripts/inspect_owner_action_audit.py --limit 20`
7. `python3 scripts/toggle_current_session_smoke.py --disable --yes`

### NoneBot Runtime Wiring Check

在当前 AstrBot/API 聊天窗口里，**不能**替代 `yangyang_nonebot_mvp` 的真实 NoneBot runtime，也不能直接当作真实 `bot/event` 去做 smoke。

先跑只读接线检查：

```bash
python3 scripts/check_nonebot_runtime_ready.py
```

说明：
- 只读检查，不启动 bot。
- 不连接 OneBot。
- 不发送消息。
- 不修改配置。
- 不开放跨群。
- 若存在 `.env`，只检查 key 是否存在，不打印敏感 value。

当前建议的真实 smoke 前流程：
1. `python3 scripts/check_nonebot_runtime_ready.py`
2. `python3 scripts/toggle_current_session_smoke.py --enable --yes`
3. `python3 scripts/check_current_session_smoke_ready.py`
4. `python3 scripts/run_current_session_smoke_rehearsal.py --mock-send`
5. 启动 NoneBot / OneBot runtime
6. `python3 scripts/inspect_owner_action_audit.py --tail-follow`
7. 去 QQ **当前会话**发送 `/yy-smoke-current 回应小维`
8. `python3 scripts/toggle_current_session_smoke.py --disable --yes`


真实 smoke 前，先跑本地彩排脚本：

```bash
python3 scripts/run_current_session_smoke_rehearsal.py
python3 scripts/run_current_session_smoke_rehearsal.py --mock-send
python3 scripts/run_current_session_smoke_rehearsal.py --command "/yy-smoke-current 去群里劝和一下" --mock-send
```

说明：
- 只使用 mock bot / mock event / mock recent messages。
- 不连接 QQ / OneBot。
- 不发送真实消息。
- 不修改配置。
- 默认命令是 `/yy-smoke-current 回应小维`。
- 默认不加 `--mock-send` 时走 `dry_run=true`：不会调用 mock `bot.send`，也不会污染 dedup。
- 加 `--mock-send` 也只是调用本地 mock `bot.send`，用于彩排非 dry-run 链路，不是真实 QQ 发送。
- `--command "/yy-smoke-current 去群里劝和一下"` 这类跨群路径仍会输出 `cross_session_blocked`。

推荐真实 smoke 前顺序：
1. `python3 scripts/toggle_current_session_smoke.py --enable --yes`
2. `python3 scripts/check_current_session_smoke_ready.py`
3. `python3 scripts/run_current_session_smoke_rehearsal.py --mock-send`
4. `python3 scripts/inspect_owner_action_audit.py --tail-follow`
5. 去 QQ 当前会话发送 `/yy-smoke-current 回应小维`
6. 测完后 `python3 scripts/toggle_current_session_smoke.py --disable --yes`

### Manual Smoke 调用示例与 Audit 查看

### Smoke 配置一键开关与回滚

先用脚本切换 `runtime_config.json`，不要手改 JSON。该脚本只改本项目配置文件，不连接 QQ / OneBot，不发送消息，不开放跨群。

常用命令：

```bash
python3 scripts/toggle_current_session_smoke.py --show
python3 scripts/toggle_current_session_smoke.py --enable --dry-run
python3 scripts/toggle_current_session_smoke.py --enable --yes
python3 scripts/check_current_session_smoke_ready.py
python3 scripts/toggle_current_session_smoke.py --disable --yes
python3 scripts/toggle_current_session_smoke.py --restore backups/runtime_config/xxx.json --yes
```

说明：
- `--enable` 只开启当前会话 manual smoke 必需开关。
- enable / disable 默认都会先自动备份到 `backups/runtime_config/`。
- enable 后**仍不会自动发送**，还必须在代码里的 manual smoke 分支显式传 `explicit_enable=True`，并注入当前 `bot` / `event`。
- `send_group_message` / 跨群 / cross-session 相关能力仍锁死。

smoke 前检查清单：
- 终端1先开只读 audit 观察：`python3 scripts/inspect_owner_action_audit.py --tail-follow`
- 终端2再跑：`python3 scripts/check_current_session_smoke_ready.py`
- 确认 `owner_action_manual_smoke_enabled` / `owner_action_nonebot_sender_enabled` / `owner_action_current_session_delivery_enabled`
- 确认 `owner_action_delivery_audit_path`
- 确认 `owner_action_delivery_dedup_ttl_seconds`
- 确认跨群仍锁死

smoke 后检查清单：
- `python3 scripts/inspect_owner_action_audit.py --limit 20`
- `python3 scripts/inspect_owner_action_audit.py --real-send-only`
- `python3 scripts/inspect_owner_action_audit.py --duplicates-only`
- 检查 `real_send`、`duplicate`、`reason`、`content_preview`

审计查看：
- 默认：`logs/owner_action_delivery_audit.jsonl`
- 普通查看：`python3 scripts/inspect_owner_action_audit.py --limit 20`
- 实时只读观察：
  - `python3 scripts/inspect_owner_action_audit.py --tail-follow`
  - `python3 scripts/inspect_owner_action_audit.py --tail-follow --real-send-only`
  - `python3 scripts/inspect_owner_action_audit.py --tail-follow --duplicates-only`
- 推荐真实 smoke 时开两个终端：
  - 终端1：`--tail-follow` 实时看 audit
  - 终端2：跑 ready check / 手动触发 smoke
- 该工具只读，不发送消息，不开放跨群

回滚：
- 关闭 `owner_action_manual_smoke_enabled`，或
- 关闭 `owner_action_nonebot_sender_enabled`，或
- 关闭 `owner_action_current_session_delivery_enabled`
- 然后重启

强调：
- 当前阶段 `send_group_message` / `destination_type=group` 仍锁死
- 当前阶段绝不测试跨群

## 本地联调步骤

### 1. 复制环境变量模板

```bash
cp .env.example .env
```

然后按你的 OneBot 实际配置填写 `.env`。

注意：
- 不要提交真实 API Key
- `YANGYANG_DRY_RUN=1` 时不会真实调模型，也不会真实发消息
- dry_run 仍会跑完整主链路，适合先验证收消息、判定、入库、冷却

### 2. dry_run 启动

先保持：

```bash
YANGYANG_DRY_RUN=1
```

然后启动：

```bash
python3 bot.py
```

### 3. 连接 OneBot

本项目当前按 OneBot v11 联调，常见方式有两种：

- **反向 WebSocket**：让协议端连接 NoneBot
- **正向 HTTP / WebSocket**：由 NoneBot 连接协议端

`.env.example` 里只提供最小占位字段，实际使用时以你的协议端为准。至少要保证：

- NoneBot 能正常启动
- OneBot v11 adapter 已注册
- 协议端与 NoneBot 地址/token 对得上

如果你使用 napcat、Lagrange 或其他 OneBot v11 实现，按各自文档把地址和 token 配好即可。

### 4. 测试群里 @bot

联调建议顺序：

1. 先启动协议端
2. 再启动 `python3 bot.py`
3. 在测试群里发送一条明确 `@bot` 的消息
4. 观察日志是否进入插件主链路
5. 检查 `src/plugins/yangyang/data/chat_history.db` 是否有消息入库

当前硬规则下：

- 私聊：会回复
- owner 群聊 `@bot`：最高优先级放行
- owner 明确命令白名单：会回复，即使不 `@bot`
  - 当前 MVP 关键词示例：`回应`、`回复`、`回一下`、`评价`、`锐评`、`帮我说`、`去群里`、`劝和`、`纠错`、`补刀`、`接一下`、`看一下`
- 群聊明确 `@bot`：会回复
- 群聊 `quote/reply bot` 但不 `@bot`：会 `SKIP`，但消息仍入库
- 群聊 `quote/reply bot` 且同时 `@bot`：允许回复
- 其它群聊：默认静默
- 但普通群聊回复前会先做 bot loop 防护：
  - 仅作用于群聊普通链路
  - 最近 `behavior.bot_loop_recent_limit` 条消息里，若已知 bot 消息数达到 `behavior.bot_loop_min_bot_messages`，且存在多个 bot 交替发言，则当前回复会被 SKIP
  - 触发后会给该群设置 `behavior.bot_loop_cooldown_seconds` 秒群级冷却
  - 普通人 `@bot` 不会被误杀
  - 已知 bot `@bot` 会优先被 loop 防护拦截，避免双 bot 死循环

### 5. 切换真实模型调用

把：

```bash
YANGYANG_DRY_RUN=0
```

并至少配置一组：

```bash
OPENAI_API_KEY=xxx
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
```

或：

```bash
DEEPSEEK_API_KEY=xxx
DEEPSEEK_BASE_URL=https://your-deepseek-compatible-endpoint/v1
```

不要在代码里写死 token / key。

## 当前红线

- 不主动水群
- 不接管 AstrBot 生产
- 不做 LLM 裁判
- 不做 TTS
- 不做长期记忆检索

本轮补充 owner 指令硬规则：
- owner/阿漂在群聊中 `@bot`：直接进入回复判定，优先级最高
- owner/阿漂明确命令白名单：即使不 `@bot` 也允许进入回复判定
- 白名单采用硬规则关键词匹配，不交给 LLM
- 普通群友即使使用相同动词，也不能借此解锁 bot 回复资格
- owner 明确指令不受普通 quote/reply 静默与普通 bot loop 误杀
- 仍保留极端安全兜底：空消息/无有效内容不回复

本轮补充 quote/reply 触发规则：
- 群聊中，仅引用 bot 上一条消息不构成回复资格
- 必须同时 `@bot`，或 owner/阿漂明确指令，才允许触发回复
- 普通群聊非 `@` + quote bot：应 `SKIP`，但消息仍入库
- 私聊不受 quote/reply 规则影响

本轮只做 quote/reply 触发规则，不改主动水群，不做 LLM 裁判，不做 TTS。

本轮补充 OwnerAction Router MVP：
- 仅做 owner 指令解析，不接真实发送
- owner 风格型指令补充 fallback：命中 `补刀/锐评/纠错/更正/评价/劝和` 等明确处理意图，但未命中显式 action 时，默认归入 `reply_current`
- 已补最小 `target_user_id` 解析：显式 QQ / 别名 / 真实 @ 非 bot 用户
- `member_aliases` 默认内置 `小维/红尘/娅娅`，但仍走运行时配置，可继续改
- 已接入主 pipeline 的安全观察位，但仍不执行
- `send_group_message` 新增最小 `target_group_id` 解析：
  - 显式纯数字群号优先
  - 群聊里优先取当前 `group_id`
  - owner 私聊未写群号时回退 `default_group_id` / `primary_group_id`
  - 无法解析时保持 `target_group_id=None` 并写入 `no_target_group`
- `dry_run` 下会在模拟回复 / debug 输出中附加结构化摘要
  - 示例：`[dry_run][owner_action] action=send_group_message style=mediate target_group=... reason=...`
- 非 `dry_run` 下仅记录 / 挂载到上下文，不触发跨会话发送
- 当前 OwnerAction 只进入 prompt context 与 dry_run 摘要，仍未接入执行层
- 不做跨会话主动消息
- 不改变现有主链路执行行为
- 下一步如需接入执行层，再单独把解析结果挂到安全链路

## 当前检查

```bash
python3 scripts/check_project.py
```

当前策略：
- 若环境未安装 nonebot，不强行启动真实 bot
- 先做语法编译与离线 mock 检查

## 当前检查结果

以本地执行结果为准。


## 本轮补充：OwnerAction Executor Stub MVP

- 新增 `src/plugins/yangyang/core/owner_action_executor.py`
- 新增 `OwnerActionExecutionPlan` 与纯函数 `build_owner_action_execution_plan(action, gate_result, message, config)`
- 当前只生成执行计划 stub，不真实执行，不调用真实 sender，不调用 `bot.send*` 发跨会话消息
- `real_send` 当前恒为 `False`
- 已接入主 pipeline 观察位：
  - 若存在 `msg.owner_action_gate`，会继续生成并挂载 `msg.owner_action_execution_plan`
  - `dry_run` 下追加摘要：`[dry_run][owner_action_executor] action=... destination=... status=... real_send=false reason=...`
  - 非 `dry_run` 下仅挂载/日志，不真实执行
- 当前状态：**executor stub 已完成，但仍未接真实 sender**

## OwnerAction 执行权限开关说明

本轮已加入 OwnerAction 执行权限配置 MVP：

- `owner_action_execution_enabled`
- `owner_action_allow_send_group_message`
- `owner_action_allow_reply_current`
- `owner_action_allow_internal_control`

当前默认全部关闭。

注意：
- 这些开关当前只影响 gate / execution_plan 的可见状态
- 便于 dry_run 观察“结构有效，但执行被配置禁止”
- 本轮 **不会** 打开真实 sender / `bot.send`
- 无论配置如何，`owner_action_executor` 生成的 `real_send` 仍恒为 `False`


- OwnerAction Reply Draft MVP：已新增 `owner_action_reply_draft` 草稿层；当前只生成待发送草稿与 dry_run 摘要可见，不真实发送，`real_send` 仍恒为 `False`。
