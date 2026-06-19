# NoneBot 秧秧新内核 MVP 开发进度

## 1. 项目目标
当前项目目标是先跑通 NoneBot 新内核下的最小可用链路，形成一个**可收消息、可判定、可调模型、可发送、可入库、可冷却、可防 bot 互聊死循环**的 MVP。

本阶段只做第一阶段能力，重点是：
- 适配 OneBot v11 群聊/私聊消息事件
- 将消息统一归一化并写入 SQLite
- 通过硬规则决定是否回复
- 组装基础 prompt（人设 + 公开/私密记忆 + 最近上下文）
- 走 OpenAI 兼容接口调用模型
- 发送回复并把 bot 回复再次入库
- 维护基础冷却、主动上限、失败降级

明确**不在本阶段处理**：
- 主动水群
- LLM 裁判
- TTS
- 长期记忆检索
- 接管 AstrBot 现网生产链路

---

## 2. 当前目录
项目根目录：
`/AstrBot/data/workspaces/default_FriendMessage_335059272/yangyang_nonebot_mvp`

本轮补齐后目录结构已扩展为：
- `README.md`
- `PROJECT_PROGRESS.md`
- `pyproject.toml`
- `.env.example`
- `.gitignore`
- `bot.py`
- `scripts/check_project.py`
- `src/plugins/yangyang/__init__.py`
- `src/plugins/yangyang/admin/runtime_config.py`
- `src/plugins/yangyang/core/`
- `src/plugins/yangyang/memory/`
- `src/plugins/yangyang/output/`
- `src/plugins/yangyang/tasks/`
- `src/plugins/yangyang/data/runtime_config.json`
- `src/plugins/yangyang/data/chat_history.db`
- `tests/mock_pipeline_test.py`

其中：
- `src/plugins/yangyang/` 仍是 MVP 主体代码
- `bot.py` 是本轮新增的**独立 NoneBot 启动入口**
- `tests/mock_pipeline_test.py` 是**不依赖真实 NoneBot 启动**的离线 mock 测试脚本
- `tests/test_owner_action_e2e_dryrun.py` 是 **OwnerAction 端到端 dry_run 场景测试**
- `scripts/check_project.py` 是一键检查脚本
- `pyproject.toml` 负责最小项目脚手架

---

## 3. 已完成模块清单
### 3.1 本轮新增：Host Handoff Release Package MVP

已完成：
- 新增交接打包脚本：`scripts/build_host_handoff_package.sh`
  - 目标：在当前开发环境生成给宿主机 / 娅娅笔记本测试用的安全交接压缩包
  - 支持：`--dry-run`、`--check-only`、`--output-dir`、`--name`、`--include-tests`、`--no-tests`
  - 默认输出到 `dist/`
  - 默认文件名：`yangyang_nonebot_mvp_host_handoff_YYYYMMDD-HHMMSS.tar.gz`
  - 同时生成 manifest 与 sha256 文件
  - 默认包含：源码、脚本、文档、部署说明、`.env.example`、`pyproject.toml`、`PROJECT_PROGRESS.md`、`tests/`
  - 默认排除：`.env`、`.venv/`、`venv/`、`__pycache__/`、`.pytest_cache/`、`.git/`、`logs/`、`dist/`、`src/backups/`、`*.db`、`*.sqlite*`、`*.log`、`*.pyc`、`*.tmp`、`*token*`、`*secret*`、`*apikey*`
  - 打包前后均执行路径级安全扫描；若发现敏感项则直接 FAIL 并删除生成物
- 新增文档：`docs/host_handoff_package.md`
  - 说明如何在当前开发环境生成交接包
  - 说明如何通过宝塔下载 `dist/*.tar.gz`
  - 说明在娅娅笔记本解压到 `/opt/yangyang_nonebot_mvp`
  - 明确宿主机解压后先跑 `bash scripts/host_preflight_check.sh`
  - 指向 `deploy/host_deploy_checklist.md` 与 `deploy/napcat_reverse_ws_host_checklist.md`
  - 明确 `.env` 必须在宿主机从 `.env.example` 复制生成，不随包提供
  - 明确 token 不进压缩包；debug bundle 回传流程后续补充
- 更新 `README.md`
  - 在宿主机部署入口加入“生成交接包”小节
  - 新增 `docs/host_handoff_package.md` 链接与示例命令
- 更新 `deploy/host_deploy_checklist.md`
  - 在项目复制 / 拉取方式处补充“通过宝塔下载交接包”的方式
  - 新增 `docs/host_handoff_package.md` 链接
- 新增测试：`tests/test_host_handoff_package.py`
  - 覆盖脚本存在、`bash -n`、文档链接、`--dry-run`、`--check-only`
  - 覆盖固定输出目录生成测试包、manifest / tar 内容安全检查、`.env.example` 必须包含、测试后清理
- 本轮只修改脚本 / 文档 / 测试
- 未安装依赖、未创建当前容器 `.venv`、未启动 bot、未连接 NapCat / OneBot、未发送消息、未修改 runtime smoke 开关

### 3.1 本轮新增：NapCat Reverse WS Host Checklist + Yaya Laptop Deploy Notes MVP

已完成：
- 新增宿主机落地文档：`deploy/napcat_reverse_ws_host_checklist.md`
  - 明确适用场景：宿主机 / 旧笔记本 Ubuntu 裸机运行 NoneBot，NapCat 通过 OneBot v11 反向 WebSocket 主动连接 NoneBot
  - 明确当前 Docker / AstrBot 开发容器只用于开发、mock、只读检查，不用于真实连接
  - 补齐同机 / 分机推荐拓扑，覆盖 `ws://127.0.0.1:8080/onebot/v11/ws` 与 `ws://192.168.x.x:8080/onebot/v11/ws`
  - 补齐启动顺序、端口监听、URL path、token/secret、防火墙、日志判断、故障排查矩阵
  - 补充“娅娅笔记本”部署注意事项：不建议默认长期 root、避免与 AstrBot 端口/日志/数据目录冲突、建议使用 `yangyang-nonebot.service` 与 `journalctl`
- 更新 `docs/napcat_onebot_setup.md`
  - 增加新 checklist 链接
  - 增加“部署到娅娅笔记本时优先按同机拓扑检查”的说明
- 更新 `deploy/host_deploy_checklist.md`
  - 在 OneBot / NapCat 对接阶段加入 `deploy/napcat_reverse_ws_host_checklist.md`
  - 增加“娅娅笔记本部署”简短入口
- 更新 `README.md`
  - 在宿主机部署入口加入 `deploy/napcat_reverse_ws_host_checklist.md`
  - 增加娅娅笔记本宿主机部署时不要默认长期 root、注意 AstrBot 资源冲突的提醒
- 新增测试：`tests/test_napcat_reverse_ws_host_checklist.py`
  - 覆盖新文档存在、关键字符串、README/docs/deploy 链接与敏感信息泄露检查
- 本轮只修改文档 / 轻量测试 / 链接收口
- 未安装依赖、未创建当前容器 `.venv`、未启动 bot、未连接 NapCat / OneBot、未发送消息、未修改 runtime smoke 开关

### 3.1 本轮新增：NapCat / OneBot v11 Connection Adaptation Prep MVP

已完成：
- 新增接入文档：`docs/napcat_onebot_setup.md`
  - 推荐优先使用 **反向 WebSocket**：NapCat 主动连接 NoneBot
  - 给出 `ws://127.0.0.1:8080/onebot/v11/ws` 占位，并说明分机部署时应改为宿主机局域网 IP
  - 整理 NapCat 侧 OneBot v11 / WebSocket / access token / secret 占位
  - 整理 `.env` 中真实 NoneBot 生效 key 与文档辅助 `NAPCAT_*` key 的边界
  - 补充正向 WebSocket 备选、安全注意、故障排查
- 收紧 `.env.example`
  - 新增 NapCat / OneBot v11 分区
  - 保留 `DRIVER`、`HOST`、`PORT`、`LOG_LEVEL`、`ONEBOT_ACCESS_TOKEN`、`ONEBOT_SECRET` 等关键 key
  - 增加 `NAPCAT_CONNECTION_MODE=reverse_ws`、`NAPCAT_REVERSE_WS_URL=ws://127.0.0.1:8080/onebot/v11/ws` 文档辅助占位
  - 不写真实 token
- 新增只读检查脚本：`scripts/check_napcat_onebot_config.py`
  - 支持 `--root` / `--env` / `--example`
  - 只读检查 `.env` / `.env.example` / `bot.py` / `pyproject.toml`
  - 检查依赖声明、OneBot v11 adapter 注册、`.env` 加载、插件目录加载、关键 env key、推荐 `reverse_ws` 模式、安全占位
  - 输出固定头 `[NAPCAT_ONEBOT_CONFIG_CHECK]` 与 `[PASS]/[WARN]/[FAIL]` 行
  - 有 FAIL 返回 1；只有 PASS/WARN 返回 0
  - 不联网、不监听端口、不启动 bot、不打印 `.env` value
- 更新 `README.md`
  - 在首页三入口 / 宿主机部署区域新增 `docs/napcat_onebot_setup.md` 链接
  - 新增 `python3 scripts/check_napcat_onebot_config.py` 与宿主机 `.venv/bin/python scripts/check_napcat_onebot_config.py` 命令
- 更新 `deploy/host_deploy_checklist.md`
  - 在 `.env` / OneBot 对接阶段加入 `docs/napcat_onebot_setup.md`
  - 增加 `.venv/bin/python scripts/check_napcat_onebot_config.py`
  - 强调通过检查后再启动 NoneBot
- 更新 `docs/current_session_smoke_example.md`
  - 真实 smoke 前新增 NapCat config check
- 本轮未安装依赖、未创建当前容器 `.venv`、未启动 bot、未连接 NapCat/OneBot、未发送消息、未修改 runtime smoke 开关

### 3.1 本轮新增：README Three-Entry Landing Page MVP

已完成：
- 调整 `README.md` 首页结构，新增靠前的“三入口”收口区块：
  - 开发 / 单测 / mock rehearsal（当前容器可执行）
  - 宿主机部署（真实运行环境）
  - 真实 current-session smoke（必须等 NoneBot + OneBot 已连接）
- README 顶部补充安全声明：
  - 当前 AstrBot/API 聊天窗口不能替代真实 NoneBot runtime 的 `bot/event`
  - `current-session smoke` 默认关闭
  - 普通 owner action 不自动真发
  - 普通 `回应小维` 不会触发真实 smoke
  - 跨群 `send_group_message` 仍锁死
- 首页三入口已分别补齐推荐命令与边界：
  - 当前容器只做开发 / 单测 / mock rehearsal / 只读检查
  - 宿主机入口明确链接 `docs/host_nonebot_install.md` 与 `deploy/host_deploy_checklist.md`
  - 真实 smoke 入口明确链接 `docs/current_session_smoke_example.md`，并强调测试后立即 disable
- 轻量合并 README 内原有安装入口，避免把开发容器 mock/脚本误当成真实 NoneBot runtime
- 新增测试：`tests/test_readme_three_entry.py`
  - 覆盖 README 三入口标题/关键词
  - 覆盖三个关键链接
  - 覆盖真实 `bot/event` 提示
  - 覆盖“不要在当前容器执行真实安装”提示
  - 覆盖普通 `回应小维` 不触发真实 smoke
  - 覆盖测试后 disable 提示
  - 覆盖 README 不含真实 token/secret/api key 明文
- 本轮未安装依赖、未创建 `.venv`、未启动 bot、未连接 OneBot、未发送消息、未修改 runtime smoke 开关

### 3.1 本轮新增：NoneBot Runtime Wiring Check MVP

已完成：
- 新增只读检查脚本：`scripts/check_nonebot_runtime_ready.py`
- 检查范围严格限制为静态/只读接线状态：
  - 文件存在性：`bot.py` / `pyproject.toml` / `.env.example` / plugin init / smoke trigger / sender 相关文件
  - Python compile：优先 AST/compile，避免 import `bot.py` 触发 NoneBot 初始化副作用
  - 依赖检查：静态检查 `pyproject.toml` 的 nonebot/onebot 依赖声明；动态检查 `import nonebot` / `import nonebot.adapters.onebot.v11`
  - 配置检查：`.env` 是否存在；`.env.example` 是否包含 driver/host/port/websocket 等提示；`.env` 只打印 key，不打印 value
  - runtime_config 安全态检查：默认 smoke 开关是否回到 `owner_action_manual_smoke_enabled=false`
  - 插件加载检查：`bot.py` 是否 load `src/plugins`；是否注册 OneBot v11 adapter；`__init__.py` 是否引用 smoke trigger hook 与 bot/event 入口
  - 安全检查：普通 owner action 是否仍为 prefix gate；跨群 send_group_message 是否继续锁死；audit path 是否存在或父目录可创建
- 输出格式：
  - 头部固定 `[NONEBOT_RUNTIME_READY_CHECK]`
  - 单行 `[PASS]/[WARN]/[FAIL]`
  - summary 统计与 fail=1 返回码
- 不启动真实 bot，不连接 OneBot，不发送消息，不修改配置，不开放跨群
- 新增测试：`tests/test_check_nonebot_runtime_ready.py`
  - 覆盖脚本可运行
  - 覆盖 header 输出
  - 覆盖 `.env` value 不泄露
  - 覆盖缺少 `.env` 只 WARN
  - 覆盖临时 root 缺关键文件会 FAIL
  - 覆盖 runtime smoke 开启时输出 WARN
- 更新 `README.md` 与 `docs/current_session_smoke_example.md`
  - 在真实 smoke 前新增 runtime wiring check
  - 明确当前 AstrBot/API 窗口不能替代真实 NoneBot runtime 的 `bot/event`

### 3.1 本轮新增：Current-Session Smoke Rehearsal Runner MVP

已完成：
- 新增本地彩排脚本：`scripts/run_current_session_smoke_rehearsal.py`
- 默认命令：`/yy-smoke-current 回应小维`
- 支持参数：
  - `--command TEXT`
  - `--mock-send`
  - `--config PATH`
  - `--reset-dedup`
  - `--no-reset-dedup`
  - `--source-message-id`
- 默认不加 `--mock-send` 时走 `dry_run=True`
  - 不调用 mock `bot.send`
  - 不污染 dedup
- `--mock-send` 时走非 dry-run 路径
  - 仍只调用本地 mock `bot.send`
  - 不连接真实 QQ / OneBot
  - 不发送真实消息
- 彩排脚本完整复用既有真实模块：
  - `handle_current_session_smoke_trigger_if_matched(...)`
  - trigger 内部复用 `run_current_session_manual_smoke_if_enabled(...)`
  - integration / factory / delivery / safety / audit 全链路复用
- mock 数据已满足：
  - owner message `is_owner=True`
  - 固定 source message id，便于 dedup 观察
  - recent messages 含“小维”相关消息，支持 `回应小维`
  - mock bot 记录 send 次数与内容
  - mock event 仅保留最小字段
  - 不查真实数据库
- 输出已补齐：
  - `config_path`
  - `command`
  - `dry_run` / `mock_send`
  - `trigger_result.matched/enabled/eligible/attempted/delivered/real_send/reason/inner_text/manual_smoke_reason/audit_path`
  - `mock_send_count`
  - 有发送时输出 `content_preview`
  - 本地彩排 / 不连 QQ / 不开放跨群提醒
- 新增测试：`tests/test_current_session_smoke_rehearsal.py`
  - 覆盖默认关闭 blocked
  - 覆盖全开 + `--mock-send` 单次 mock send
  - 覆盖默认 dry_run 不发且不污染 dedup
  - 覆盖跨群 `cross_session_blocked`
  - 覆盖无前缀 `matched=false`
  - 覆盖中文前缀 `/秧秧smoke`
- 更新 `README.md`
  - 新增 “Current-Session Smoke Rehearsal Runner” 小节
  - 补充真实 smoke 前推荐流程：toggle enable -> ready check -> rehearsal --mock-send -> audit tail-follow -> QQ 当前会话带前缀命令 -> toggle disable
- 更新 `docs/current_session_smoke_example.md`
  - 在真实 smoke 前加入 rehearsal runner
  - 明确默认 dry_run 不登记 dedup
  - 明确 `--mock-send` 也只是 mock bot，不是真实 QQ

### 3.1 本轮新增：Manual Smoke Trigger Hook MVP

已完成：
- 新增 `src/plugins/yangyang/output/current_session_smoke_trigger.py`
- 新增 `CurrentSessionSmokeTriggerResult` 与前缀命令解析
- 支持触发前缀：
  - `/yy-smoke-current`
  - `/秧秧smoke`
  - 支持前缀后全角空格
- 新增受控入口：`handle_current_session_smoke_trigger_if_matched(...)`
- trigger 规则已收紧：
  - 无前缀直接 `matched=false`
  - inner text 为空 -> `empty_inner_text`
  - 非 owner -> `not_owner`
  - manual smoke 开关未开 -> `smoke_disabled`
  - 缺 bot/event -> `missing_bot_event`
  - inner text 重新按 owner action 解析
  - 仅允许 `reply_current/current_session`
  - `send_group_message` / `group` -> `cross_session_blocked`
  - 只有 trigger 分支内部才显式传 `explicit_enable=True`
  - trigger 层不直接 `bot.send`
  - dry_run 不发送且不污染 dedup
- `src/plugins/yangyang/__init__.py` 已增加极窄 trigger hook：
  - 只有消息命中 smoke 前缀时才进入
  - 普通 owner action 仍不会自动真发
  - 默认配置仍关闭，不接管生产
- 新增测试：`tests/test_current_session_smoke_trigger.py`
  - 覆盖无前缀 / 非 owner / disabled / empty inner text / missing bot-event
  - 覆盖 full enable 单次发送 + audit
  - 覆盖 duplicate_blocked
  - 覆盖 dry_run 不登记 dedup
  - 覆盖跨群 blocked
  - 覆盖中文前缀
  - 覆盖普通 `回应小维` 不触发真实 smoke
- 更新 `README.md` 与 `docs/current_session_smoke_example.md`
  - 改为带前缀触发话术
  - 明确普通 owner action 不自动真发
  - 补充 toggle -> ready check -> tail-follow -> 带前缀触发 -> inspect audit -> disable 的完整流程

### 3.1 本轮新增：Current-Session Smoke Config Toggle MVP

已完成：
- 新增安全配置切换脚本：`scripts/toggle_current_session_smoke.py`
  - 支持 `--show` / `--enable` / `--disable` / `--dry-run` / `--yes` / `--backup` / `--restore` / `--config`
  - enable 只开启当前会话 manual smoke 所需开关
  - disable 关闭危险开关，恢复安全态
  - enable / disable 默认写前自动备份到 `backups/runtime_config/runtime_config.YYYYMMDD-HHMMSS.json`
  - restore 会校验备份 JSON 可读并输出恢复后状态
  - 输出 changed keys / smoke ready 关键开关 / explicit_enable 与 bot/event 注入提醒 / 跨群仍锁死提醒
  - 不连接 QQ / OneBot，不发送消息，不开放跨群
- 新增测试：`tests/test_toggle_current_session_smoke.py`
  - 覆盖 show / enable dry-run / enable yes / disable yes / 自动备份 / restore / 无 yes 取消 / 输入 n 取消 / 不开启 cross-session 字段
- 更新 `README.md`
  - 新增“Smoke 配置一键开关与回滚”小节与命令示例
  - 强调 enable 后仍需 `explicit_enable=True` + `bot/event` 注入，且跨群仍锁死
- 更新 `docs/current_session_smoke_example.md`
  - smoke 前加入 toggle 脚本步骤
  - smoke 后加入 disable / restore 回滚步骤

### 3.1 本轮新增：Audit Tail-Follow 只读观察模式 MVP

已完成：
- 扩展 `scripts/inspect_owner_action_audit.py`
  - 新增 `--tail-follow` 实时只读观察模式，类似 `tail -f`
  - 新增 `--poll-interval`、`--follow-timeout`、`--no-initial`
  - 启动时输出 `path / tail_follow / poll_interval / timeout`
  - 默认仍读取 `owner_action_delivery_audit_path`，支持 `--path` 覆盖
  - 文件不存在时友好提示，并在 tail-follow 下继续等待文件出现直到 timeout / Ctrl+C
  - 初始阶段可先显示最近 `--limit` 条，再持续输出新增记录
  - 兼容现有过滤参数：`--real-send-only`、`--duplicates-only`、`--action-type`、`--status`、`--mode`
  - 坏 JSON 行会跳过并计数，不会炸脚本
  - Ctrl+C / timeout 均优雅退出，返回码 0
  - 全程只读，不连接 QQ / OneBot，不发送消息，不开放跨群
- 扩展测试：`tests/test_inspect_owner_action_audit.py`
  - 覆盖 tail-follow 文件不存在 + timeout
  - 覆盖 tail-follow 输出已有记录
  - 覆盖 tail-follow 过滤参数生效
  - 覆盖坏 JSON 行不炸
  - 覆盖运行时追加一行可被 tail-follow 捕获
- 更新 `README.md`
  - 补充 tail-follow 用法
  - 补充双终端 smoke 建议
  - 强调只读、不发送、不开放跨群
- 更新 `docs/current_session_smoke_example.md`
  - 增加 smoke 前先开 tail-follow 建议
  - 增加试发后检查 `real_send / duplicate / reason` 提示

### 3.1 本轮新增：Current Session Smoke Runtime Reload Patch

已完成：
- 修补 `src/plugins/yangyang/__init__.py` 的 current-session smoke 入口时序
  - 在收到消息后尽早解析 `parse_current_session_smoke_trigger_command(...)`
  - 若命中 smoke prefix，先执行 `cfg.reload()` 读取磁盘最新 `runtime_config.json`
  - 增加日志：`yangyang plugin: current-session smoke trigger matched uid=... channel=... reload_status=... enabled=... dry_run=...`
  - smoke prefix 命中后，不再被普通 `decision.should_reply == False` 的默认静默分支提前吞掉
  - 命中后优先走 `handle_current_session_smoke_trigger_if_matched(...)`，并传入真实 `bot/event` 与 `_is_dry_run_enabled()`
- 保持安全边界不变：
  - 非 owner 仍 `not_owner`
  - `owner_action_manual_smoke_enabled=false` 仍阻断
  - dry-run 仍不真实发送
  - `send_group_message` / 跨群路径仍 `cross_session_blocked`
  - 未开放跨群 `send_group_message`
- 新增测试：`tests/test_current_session_runtime_reload_patch.py`
  - 覆盖 RuntimeConfig `reload()` 读取磁盘 toggle 后新值
  - 覆盖 smoke prefix 即使处于 default silent 也会调用 smoke handler
  - 覆盖 `not_owner`
  - 覆盖 `dry_run_no_delivery`
  - 覆盖 `cross_session_blocked`
- 更新 `docs/current_session_smoke_example.md`
  - 说明补丁后 toggle enable/disable 无需重启 NoneBot 即可让 smoke gate 读取新开关
  - 同时强调代码补丁首次落地仍需重启 NoneBot 加载新代码
- 新增补丁说明：`PATCH_NOTES_current_session_smoke_reload.md`
- 本轮未安装依赖、未启动 bot、未连接 NapCat/OneBot、未发送消息、未将 runtime smoke 开关改为 enabled

### 3.1 本轮新增：Current-Session Manual Smoke 调用示例

已完成：
- 新增文档：`docs/current_session_smoke_example.md`
  - 明确 manual smoke 仅是当前会话小范围实测入口
  - 补充 NoneBot 事件中显式调用示例
  - 强调 `explicit_enable=True` 只能放在手动 smoke 分支，不能全局默认开启
  - 列出配置全开条件、owner/current_session 限制、dry_run 语义、跨群锁死与回滚方式
- 新增 audit 查看脚本：`scripts/inspect_owner_action_audit.py`
  - 默认读取配置中的 `owner_action_delivery_audit_path`
  - 配置缺失时回退 `logs/owner_action_delivery_audit.jsonl`
  - 支持 `--path`、`--limit`、`--real-send-only`、`--duplicates-only`、`--action-type`、`--status`、`--mode`
  - 输出摘要统计：`total / delivered / real_send / duplicate / blocked`
  - 输出最近记录简表：`time / action_type / destination / mode-status / real_send / reason / content_preview`
  - 坏 JSONL 行会跳过并计数，不会炸脚本
  - 文件不存在时友好提示 `no audit file`
  - 不连接 QQ / OneBot，不发送消息
- 新增测试：`tests/test_inspect_owner_action_audit.py`
  - 覆盖文件不存在、正常统计、`--limit`、`--real-send-only`、`--duplicates-only`、`--action-type`、坏 JSON 行跳过
- `README.md` 已新增“Manual Smoke 调用示例与 Audit 查看”小节
  - 增加 smoke 前检查清单 / smoke 后检查清单 / 回滚说明
- 默认配置开关未改
- 未开放跨群发送，未接管生产

### 3.2 本轮新增：Current-Session Manual Smoke Test MVP

已完成：
- 新增 `src/plugins/yangyang/output/current_session_manual_smoke.py`
- 新增 `CurrentSessionManualSmokeResult`
  - 字段：`enabled/eligible/attempted/delivered/real_send/reason/integration_mode/audit_path`
- 新增配置项并默认关闭：
  - `owner_action_manual_smoke_enabled=false`
  - `owner_action_manual_smoke_owner_only=true`
- 新增受控入口：`run_current_session_manual_smoke_if_enabled(...)`
- smoke 规则已收紧：
  - 默认 disabled
  - 必须 `explicit_enable=True`
  - 必须 owner
  - 必须已有 `owner_action` / `owner_action_reply_draft` / `owner_action_execution_plan`
  - 仅允许 `reply_current/current_session`
  - `send_group_message` / `group` 继续 blocked/cross_session_blocked
  - 缺 `bot/event` 直接 blocked
  - smoke 层本身不直接调用 `bot.send`
  - 通过后才转交 `deliver_owner_action_current_session_if_enabled(...)`
- 新增就绪检查脚本：`scripts/check_current_session_smoke_ready.py`
  - 只读配置 / 默认值
  - 不连接真实 QQ / OneBot
  - 不发送消息
  - 输出手动 smoke 开关、sender 开关、execution 开关、reply_current 开关、audit_path、dedup ttl、跨群仍锁死
- 新增测试：`tests/test_current_session_manual_smoke.py`
  - 默认 disabled
  - explicit_enable required
  - 开 smoke 但未全开配置不发送
  - 全开 + explicit_enable + owner + bot/event -> mock `bot.send` 一次
  - 非 owner blocked
  - `send_group_message/group` blocked
  - `dry_run` 不发且不污染 dedup
  - 缺 `bot/event` blocked
  - 重复 key 第二次 `duplicate_blocked`
  - 检查脚本可运行且不发送
- `README.md` 已补“当前会话手动 Smoke Test”与回滚说明
- `__init__.py` 仅补注释与显式入口提示，默认仍不调用手动 smoke，不接管生产

### 3.2 本轮新增：Current-Session Sandbox E2E Harness MVP

已完成：
- 新增 `tests/test_current_session_sandbox_e2e.py`
- 使用 mock bot / mock event / mock owner message / mock recent messages 串联完整沙盒验收链路
- 不连接真实 QQ / OneBot，不查真实数据库，不接管生产 sender
- 在测试内覆盖完整语义链：
  - owner action 解析
  - context resolver
  - mock model reply -> reply draft
  - current-session integration
  - sender factory
  - delivery
  - safety dedup
  - audit jsonl
- 已覆盖场景：
  - A 默认配置不发送
  - B 配置全开 + `explicit_enable=True` 当前会话 mock 发送成功
  - C 同一 owner 指令重复触发，第二次 `duplicate_blocked`
  - D `dry_run` 不发送且不登记 dedup，后续首次真实发送可通过
  - E `send_group_message` / 跨群路径继续锁死
  - F 普通群友同样话术不触发 owner action
- audit 校验使用临时目录 JSONL：
  - 验证日志可解析
  - 验证关键字段存在：`action_type`、`destination_type`、`status/mode`、`real_send`、`reason`、`content_preview`、`key`
- 每个场景前均 reset safety store，避免用例互相污染
- 默认生产行为未变：
  - 默认真实 sender 仍关闭
  - 不开放跨群发送
  - 不引入复杂依赖

### 3.2 本轮新增：Current-Session Delivery Safety MVP

已完成：
- 新增 `src/plugins/yangyang/core/owner_action_delivery_safety.py`
- 新增 `OwnerActionDeliverySafetyResult` / `OwnerActionDeliveryAuditRecord`
- 已实现当前会话投递防重复：按 source message / session / action / destination / content hash 生成 idempotency key
- 新增进程内 TTL 去重 store，默认 300 秒，并提供 `reset/clear` 测试辅助方法
- dry_run 下只做安全判定与审计，不登记 dedup key，不影响后续非 dry_run 真发
- 新增 JSONL 审计日志，默认路径 `logs/owner_action_delivery_audit.jsonl`，自动建目录，写失败不炸主流程
- 已接入 `current_session_delivery_integration.py`：真实投递前先做 safety check；命中 duplicate 时直接 blocked，不调用 sender
- 已补充 dry_run safety 摘要观察位：`[dry_run][owner_action_delivery_safety] ...`
- 已补配置项：
  - `owner_action_delivery_safety_enabled`
  - `owner_action_delivery_dedup_ttl_seconds`
  - `owner_action_delivery_audit_enabled`
  - `owner_action_delivery_audit_path`
- 默认真实 sender 仍关闭；不开放跨群发送；不接管生产

### 3.1 本轮新增：Current-Session Delivery Integration MVP

已完成：
- 新增当前会话真实投递集成薄层：`src/plugins/yangyang/output/current_session_delivery_integration.py`
- 新增轻量结果结构：`CurrentSessionDeliveryIntegrationResult`
  - 字段包含：`adapter_type`、`delivery_mode`、`attempted`、`delivered`、`real_send`、`reason`、`sender_enabled`
- 新增集成函数：`deliver_owner_action_current_session_if_enabled(...)`
- 集成函数规则已落实：
  - 内部固定通过 `build_owner_action_sender_adapter(config, bot, event, explicit_enable)` 取 adapter
  - 再调用既有 `deliver_owner_action_reply_draft(...)`
  - 仅处理当前会话 `reply_current/current_session`
  - 默认 `explicit_enable=False`，因此默认仍不会真实发送
  - `dry_run=True` 时强制不发送
  - 缺 `draft` / `plan` / `action` 时直接 no-op
  - `send_group_message` / `destination_type=group` 仍 blocked，不触发真实 sender
  - `internal_control` 仍 blocked/not_implemented
  - 不直接调用 `bot.send`，真实发送仍只能发生在 `NoneBotCurrentSessionSenderAdapter`
- 主 pipeline 已从“手工 factory + delivery”改为走该集成薄层
  - 保留明确注释与显式注入点
  - 默认 `explicit_enable=False`
  - 不改变普通聊天/普通回复既有行为
  - 不接管 AstrBot/NoneBot 生产
- `msg.owner_action_delivery_result` 仍保留，兼容既有 dry_run 摘要与旧测试观察位
- 新增测试：`tests/test_current_session_delivery_integration.py`
  - 默认配置 + mock bot/event + explicit_enable=False -> 不调用 bot
  - 配置全开但 explicit_enable=False -> 不调用 bot
  - 配置全开 + explicit_enable=True + reply_current/current_session + 非 dry_run -> 调用 mock `bot.send` 一次
  - `dry_run=True` -> 不调用 bot
  - `send_group_message/destination=group` -> blocked
  - `internal_control` -> blocked/not_implemented
  - 缺 `bot/event` -> Null/blocked
  - 缺 `draft/plan/action` -> no-op

### 3.2 本轮新增：NoneBot Current-Session Sender 显式注入点与开关测试 MVP

已完成：
- 新增显式 sender adapter 工厂：`src/plugins/yangyang/output/sender_adapter_factory.py`
- 新增生产 sender 总开关：`owner_action_nonebot_sender_enabled`，默认 `False`
- `RuntimeConfig.DEFAULTS` 与 `src/plugins/yangyang/data/runtime_config.json` 已同步默认关闭
- 工厂函数 `build_owner_action_sender_adapter(config, bot=None, event=None, explicit_enable=False)` 已实现
- 工厂规则保持保守：
  - 默认返回 `NullSenderAdapter`
  - `owner_action_nonebot_sender_enabled != true` -> Null
  - `owner_action_execution_enabled != true` -> Null
  - `owner_action_allow_reply_current != true` -> Null
  - `owner_action_current_session_delivery_enabled != true` -> Null
  - `explicit_enable != true` -> Null
  - 缺 `bot` 或 `event` -> Null
  - 仅全部满足时返回 `NoneBotCurrentSessionSenderAdapter(bot, event)`
- 工厂不接受 `target_group_id`，不创建跨群 sender，不实现 `send_group_message`
- 主 pipeline 已增加极小显式注入点注释，但默认 `explicit_enable=False`，运行行为不变，仍不会自动注入真实 NoneBot sender
- 新增测试：`tests/test_sender_adapter_factory.py`
  - 默认配置 -> NullSenderAdapter
  - 只开 execution 但未开 nonebot sender -> Null
  - 全开但 explicit_enable=False -> Null
  - 全开 + explicit_enable=True 但缺 bot/event -> Null
  - 全开 + explicit_enable=True + bot/event -> NoneBotCurrentSessionSenderAdapter
  - delivery 走 `reply_current/current_session` 可成功调用 mock bot
  - `send_group_message` / `destination=group` 仍 blocked，不调用 adapter
  - `dry_run` 下即使工厂返回真实 adapter，delivery 仍不调用 bot
- README 已补充“如何开启当前会话真实投递 / 如何回滚”小节

### 3.2 插件主入口
文件：`src/plugins/yangyang/__init__.py`

已完成：
- 注册 `on_message` 入口
- 限定只接收 `GroupMessageEvent` 与 `PrivateMessageEvent`
- 完成模块初始化与主链路编排
- 主流程顺序已打通：
  1. 事件适配
  2. 回复判定
  3. bot loop 防护判断（仅普通群聊链路）
  4. 静默消息入库 / 冷却判断
  5. 读取历史
  6. 当前消息入库
  7. 构造 messages
  8. 调模型 / dry_run 模拟回复
  9. 发送 / dry_run 跳过真实发送
  10. bot 回复入库与冷却记录
- 异常统一兜底日志，避免插件主流程直接炸掉

补充：
- 私聊与普通人群聊 `@bot` 仍保留强制回复规则，不会被 bot loop 防护误伤
- 新增群聊 quote/reply 硬规则：仅引用 bot 不构成回复资格，仍需同时 `@bot`
- owner/漂♂总明确指令优先级最高，不被 quote 规则误杀
- 已知 bot `@bot` 会优先走 bot loop 防护，避免互相点名后继续死循环
- 新增 `known_bot_uids` 配置，允许识别本 bot 之外的其它 bot 账号
- 新增 bot loop 配置项：`behavior.bot_loop_enabled`、`behavior.bot_loop_recent_limit`、`behavior.bot_loop_min_bot_messages`、`behavior.bot_loop_cooldown_seconds`

- owner 在群聊中 @bot：必定允许进入回复判定
- owner 使用明确命令句式要求 bot 回应某人/某条消息：必定允许进入回复判定
- owner 明确指令不受 quote/reply 静默规则、普通群聊静默规则、普通 bot loop 误杀影响
- RuntimeConfig 新增 `owner_uids`，默认包含 `335059272`，并兼容旧字段 `owner_uid`
- 明确命令句式采用硬规则白名单，不走 LLM
- 内部消息模型新增 `is_owner`、`owner_command`，兼容既有 `explicit_command`
- 扩展 mock 测试覆盖 owner @bot、owner 明确指令、普通群友相同用词、owner quote bot、不被普通 bot loop 误杀、dry_run 保持正常
- 新增 OwnerAction Router 解析测试：覆盖劝和、回应、补刀/锐评、纠错、别回/收手、普通群友无效、owner 普通闲聊无动作
- 新增 pipeline 观察位测试：覆盖 dry_run 下 owner action 摘要可见、dry_run 普通 owner 闲聊不出现摘要、非 dry_run 下不触发真实跨会话发送
- 新增 OwnerAction 端到端 dry_run 场景测试：`tests/test_owner_action_e2e_dryrun.py`
  - 覆盖 owner 指令完整链路观测：`owner_action` / `action_type` / `style` / `target_group_id` / `target_user_id`
  - 覆盖 prompt context 已包含 action 摘要
  - 覆盖 `owner_action_gate` / `owner_action_execution_plan` / `real_send=false`
  - 覆盖典型指令：
    - 私聊 `去群里劝和一下`
    - 群聊 `回应小维`
    - 群聊 `补刀娅娅`（style-only fallback 到 `reply_current`）
    - 群聊 `纠错刚才那句`（style-only fallback 到 `reply_current`）
    - 群聊 `评价小维`（style-only fallback 到 `reply_current`）
    - 群聊 `别回了，收手`
    - 群聊 `静默一下`
  - 覆盖反例：
    - 普通群友同样指令不触发 owner action
    - owner 普通闲聊不触发 owner action
    - 缺 target_group 的 `send_group_message` 会被 gate blocked，且 execution plan 为 blocked/no real send
  - 全部场景严格保持 dry_run，不接真实 sender、不调用真实跨会话发送，所有 execution_plan.real_send 均为 `False`

### 3.2 事件适配层 EventAdapter
文件：`src/plugins/yangyang/core/event_adapter.py`

已完成：
- 定义统一内部消息模型 `Message`
- 适配群聊消息 / 私聊消息
- 提取字段：
  - `msg_id`
  - `uid`
  - `nick`
  - `group_id`
  - `channel`
  - `text`
  - `raw_content`
  - `is_at_bot`
  - `is_at_owner`
  - `is_quote_bot`
  - `quote_target_msg_id`
  - `reply_to_message_id`
  - `reply_to_user_id`
  - `is_reply_to_bot`
  - `is_owner`
  - `owner_command`
  - `explicit_command`
  - `images`
  - `timestamp`
- 支持从消息段中识别 `at`、`reply`、`image`
- 支持 owner 多 UID 配置识别
- 支持 owner 明确命令白名单硬规则识别
- 支持适配失败时返回最小安全消息，避免主链路崩溃

### 3.2.1 OwnerAction Router MVP
文件：`src/plugins/yangyang/core/owner_action_router.py`

已完成：
- 新增 `OwnerAction` 轻量结构
- 新增纯函数 `parse_owner_action(message, config)`
- 仅解析 owner 消息，普通群友相同话术不生效
- 当前可识别动作：
  - `send_group_message`
  - `reply_current`
  - `cancel_reply`
  - `silence_topic`
  - `unknown`
- 新增 owner 风格指令 fallback 规则：
  - 若消息来自 owner
  - 且命中 `补刀/锐评/纠错/更正/评价/劝和` 等明确风格/处理意图
  - 但未命中 `send_group_message` / `reply_current` / `cancel_reply` / `silence_topic` 等显式 action
  - 则默认归入 `reply_current`
  - 普通群友相同话术仍不生效，owner 普通闲聊仍返回 None
- 当前可识别风格：
  - `mediate`
  - `roast`
  - `correct`
  - `comment`
  - `normal`
- RuntimeConfig 新增默认目标群字段：
  - `default_group_id`
  - `primary_group_id`
- RuntimeConfig 新增 `member_aliases`：
  - 轻量成员别名映射，如 `{"小维": "3916107556", "红尘": "2434523727", "娅娅": "2690087239"}`
- `send_group_message` 新增最小 `target_group_id` 解析能力：
  - 文本内显式纯数字群号优先
  - 群聊上下文优先复用当前 `group_id`
  - owner 私聊未写群号时可回退到默认目标群
  - 若仍无法解析，则 `target_group_id=None`，并在 `reason` 标记 `no_target_group`
- 新增最小 `target_user_id` 解析能力：
  - owner 文本显式 QQ 号优先
  - 支持 `member_aliases` 轻量别名映射，默认内置 `小维/红尘/娅娅`，仍可配置覆盖
  - 若消息里存在真实 `@` 用户列表，则优先取非 bot 自己的被 `@` 用户
  - 若仍无法解析，则 `target_user_id=None`，避免误判
- 已接入主 pipeline 的安全观察位：
  - 在判定后、模型调用前解析并挂载到 `msg.owner_action`
  - PromptBuilder 现会在 `msg.is_owner` 且存在 `owner_action` 时注入轻量结构化 context
  - 注入内容只保留 `action_type/style/target_group/target_user/reason/raw_hint` 短摘要，避免 raw_text 大段污染 prompt
  - 在判定后、模型调用前解析并挂载到 `msg.owner_action`
  - `dry_run` 模式下把结构化摘要写入日志，并附加到模拟回复中便于联调观察
  - 摘要中会显示 `target_group` 与 `target_user`
  - 非 `dry_run` 模式下仅记录 / 挂载，不执行

当前约束：
- 只做解析，不做执行
- 不接真实 sender 执行层
- 不做跨会话主动发送
- 不改变现有主链路行为
- 当前仍未接入真实执行层；OwnerAction 仅用于 prompt context / dry_run 观察
- 新增 OwnerAction Context Resolver MVP：
  - 文件：`src/plugins/yangyang/core/owner_action_context_resolver.py`
  - 新增 `OwnerActionContext` 轻量结构
  - 当前仅解析 owner 指令所针对的上下文，不真实执行
  - 支持解析来源：`quote` / `recent_by_user` / `recent_current_session` / `none`
  - quote 优先：若 owner 使用 reply/quote，则优先保留 `target_message_id` 与 `reply_to_user_id`；能命中 recent/store 时补全消息内容，否则 `summary=quote_missing_content`
  - 若 action 已解析 `target_user_id`，则回收当前会话中该用户最近 1-3 条消息，`source=recent_by_user`
  - 若无 target_user，但 action/style 明确，则回收当前会话最近 3-5 条非 owner、非 bot 消息，`source=recent_current_session`
  - 找不到上下文时返回 `source=none`，`summary=context_not_found`，不硬编
  - 已接入主 pipeline：存在 `msg.owner_action` 时会继续挂载 `msg.owner_action_context`
  - `dry_run` 下新增可见摘要：`[dry_run][owner_action_context] source=... target_user=... messages=... reason=...`
  - PromptBuilder 现仅在 `msg.is_owner` 且存在 `msg.owner_action_context` 时追加短结构化上下文
  - 注入内容默认截断；普通群友同话术不会注入；缺上下文时会提示“上下文不足，谨慎回应”
  - 当前仍严格不开放真实执行层；`execution_plan.real_send` 仍恒为 `False`
- 新增 OwnerAction 当前会话 Sender Adapter Interface MVP：
  - 文件：`src/plugins/yangyang/output/sender_adapter.py`
  - 新增统一结果结构 `SendResult`：`attempted/delivered/mode/destination_type/destination_id/content_length/reason/real_send`
  - 新增 `NullSenderAdapter`：默认安全实现，永远不发，`real_send=False`
  - 新增 `FakeSenderAdapter`：测试实现，只记录 `sent_messages`，不真实调用 bot.send
  - 新增 `NoneBotCurrentSessionSenderAdapter`：真实边界适配器，仅支持当前会话 `reply_current`，内部只走 `bot.send(event, content)`
  - 不实现 `send_group_message`，不接受外部 `group_id` 主动发群，不拼接跨会话 API
  - `owner_action_delivery.py` 改为优先接收 adapter 风格对象：`send_current_session(message, content) -> SendResult`
  - 兼容旧式 callable / legacy sender object，但默认未注入 sender 时会退回安全阻断，不真实发送
  - 主 pipeline 默认仍传 `sender=None`，不会注入真实 sender，不改变普通聊天发送路径
  - 真实 NoneBot current-session sender 默认不注入、不启用；仅在显式注入且配置全开、非 dry_run 时才可能调用
  - `send_group_message` / 跨群跨会话发送继续绝对锁死
  - 新增测试覆盖：Null/Fake sender、NoneBot current-session sender、dry_run 不调用 adapter、默认无 sender 阻断、跨群仍 blocked
- 新增 OwnerAction 当前会话受控投递层 MVP：
  - 文件：`src/plugins/yangyang/core/owner_action_delivery.py`
  - 新增 `OwnerActionDeliveryResult` 与 `deliver_owner_action_reply_draft(...)`
  - 当前只允许受控 `reply_current` → `current_session` 投递判定；默认关闭
  - RuntimeConfig 新增 `owner_action_current_session_delivery_enabled`，默认 `False`，runtime_config.json 同步关闭
  - 满足以下条件才允许尝试：
    - `action_type == reply_current`
    - `destination_type == current_session`
    - `owner_action_execution_enabled == true`
    - `owner_action_allow_reply_current == true`
    - `owner_action_current_session_delivery_enabled == true`
    - 非 dry_run
  - `send_group_message` / `group` destination 继续绝对锁死
  - `internal_control` 本轮不执行，仅返回 blocked / not_implemented
  - 未注入 sender 时仅返回 `blocked/no_sender`，不会调用真实 `bot.send*`
  - 已接入主 pipeline：
    - 在 `msg.owner_action_reply_draft` 后生成并挂载 `msg.owner_action_delivery_result`
    - `dry_run` 下追加摘要：`[dry_run][owner_action_delivery] mode=... attempted=... delivered=... real_send=... reason=...`
  - 当前生产默认配置下依旧不会触发真实 owner action 投递；真实投递仍需显式配置和 sender 注入
- 新增 OwnerAction execution gate MVP：
  - 文件：`src/plugins/yangyang/core/owner_action_gate.py`
  - 新增 `OwnerActionGateResult` 轻量结构与纯函数 `evaluate_owner_action_gate(action, message, config)`
  - RuntimeConfig 已加入执行权限配置：
    - `owner_action_execution_enabled`
    - `owner_action_allow_send_group_message`
    - `owner_action_allow_reply_current`
    - `owner_action_allow_internal_control`
  - 默认全部关闭；gate 会保留“结构有效”可见性，但标记 `safe_to_execute=False`
  - 缺目标群等结构错误仍优先返回 `missing_target_group`，不会被配置闸门掩盖
  - 默认配置下结构有效动作会进入 `mode=dry_run`，并带 `execution_disabled` / `blocked_by_config` / `permission` 等状态
  - 已接入主 pipeline：存在 `msg.owner_action` 时会挂载 `msg.owner_action_gate`
  - `dry_run` 下会附加 gate 摘要：`[dry_run][owner_action_gate] mode=... allowed=... reason=... safe=false execution_enabled=... blocked_by_config=...`
  - 非 `dry_run` 下仅记录 / 挂载上下文，不做真实跨会话执行
- 新增 OwnerAction execution plan 配置态可见性：
  - 文件：`src/plugins/yangyang/core/owner_action_executor.py`
  - 无论配置如何，本轮 `real_send` 仍恒为 `False`
  - 即便把 `owner_action_execution_enabled=true`，当前也只生成 execution plan，不调用 sender 扩展链路、不调用 `bot.send`
  - execution plan `reason` 会继承 gate 中的 `execution_disabled` / 权限状态，便于 dry_run 观察

### 3.3 决策层 DecisionEngine
文件：`src/plugins/yangyang/core/decision_engine.py`

已完成硬规则：
- 空消息 / 无有效内容：安全兜底不回复
- 私聊：直接回复
- owner/漂♂总群聊明确 @bot：允许回复
- owner/漂♂总明确命令白名单：强制放行，优先级最高
- 群聊明确 @ bot：允许回复
- 群聊 quote/reply bot：仅引用不算回复资格，仍需同时 `@bot`
- 其它群聊：默认静默

当前特点：
- owner 指令白名单不走 LLM
- 规则简单、可预期、风险低
- 已为后续扩展预留字段：
  - `reply_style`
  - `model_tier`
  - `reply_budget`
  - `target_uid`
  - `reason`
  - `is_forced`

### 3.4 冷却层 CooldownManager
文件：`src/plugins/yangyang/core/cooldown_manager.py`

已完成：
- 全局冷却
- 同话题轮次冷却
- 每日主动回复上限
- 群级 bot loop 冷却接口
- forced reply（如私聊、@bot）可跳过冷却与主动上限判断
- 自然日自动重置主动计数

当前状态：
- bot 互聊防护已从“上一条 bot 消息”升级为“最近 N 条消息窗口判定 + 群级冷却”
- 仅对普通群聊链路生效，不干扰私聊与普通人 @bot
- 已知 bot @bot 仍可被 loop 防护优先拦截，避免双 bot 死循环

### 3.5 PromptBuilder
文件：`src/plugins/yangyang/core/prompt_builder.py`

已完成：
- 基础人设 prompt 拼装
- 根据场景区分群聊 / 私聊约束
- 注入公开记忆：`/AstrBot/data/永久记忆库.txt`
- 私聊额外注入私密记忆：`/AstrBot/data/永久记忆库_私密.txt`
- 若存在成员档案，则注入目标用户 skill 摘要
- 注入最近上下文与当前用户消息

当前约束已写进 prompt：
- 不要自称 AI
- 不要解释系统规则
- 禁止若干模板句
- 群聊尽量控制在 1-2 句

### 3.6 模型路由层 ModelRouter
文件：`src/plugins/yangyang/core/model_router.py`

已完成：
- OpenAI 兼容接口调用
- 模型 tier 定义与顺序：
  - `v4_flash`
  - `v4_pro`
  - `gpt_5_5`
- 按配置判断 tier 是否启用
- 懒加载 `AsyncOpenAI`，避免未安装依赖时导入即失败
- 支持 API Key / Base URL 从环境变量或运行时配置读取
- 支持超时控制
- 支持失败冷却与向后降级
- 新增 dry_run 模式：
  - 支持 `RuntimeConfig.dry_run`
  - 支持 `YANGYANG_DRY_RUN` 环境变量覆盖
  - 返回固定模拟回复 `"[dry_run] 模拟回复：主链路已跑通。"`

当前实际可用主路径：
- 默认主要使用 `v4_flash`
- 其余 tier 现在更多是配置占位

### 3.7 记忆存储层 MemoryStore
文件：`src/plugins/yangyang/memory/store.py`

已完成：
- SQLite 建表
- `messages` 消息表
- `users` 用户基础档案表
- 消息入库
- bot 回复入库
- 用户基础信息更新
- 读取最近群聊上下文
- 支持按 channel 读取最近消息窗口 `get_recent_messages(group_id, limit, channel)`
- 新增读取最近 bot 消息接口 `get_last_bot_message()`
- 建立基础索引

当前已落地的是：
- 原始消息闭环
- 最近上下文读取
- bot loop 最近窗口判定所需的消息复用
- 用户基础计数与最后出现时间维护

仍是占位的：
- 长期记忆 entry 写入
- 上下文检索
- 用户画像增量更新

### 3.8 群友档案加载 SkillLoader
文件：`src/plugins/yangyang/memory/skill_loader.py`

已完成：
- 递归扫描 `skills` 目录
- 支持 `.skill/.md/.txt` 文件
- 尝试从文件名或正文提取 QQ 号
- 生成 `MemberSkill` 摘要对象
- 可按 uid 获取档案
- 支持 reload

当前定位：
- 作为 prompt 注入的补充资料源
- 不是完整画像系统

### 3.9 发送层 Sender
文件：`src/plugins/yangyang/output/sender.py`

已完成：
- 群聊 / 私聊发送
- 输出后处理
- 模板句清理
- 去掉前缀“秧秧:”之类冗余自称
- 群聊按预算限制句数
- 发送成功后 bot 消息入库
- 发送成功后记录冷却状态
- 新增 dry_run 发送模式：
  - 不真实调用 OneBot 发送接口
  - 仍记录 bot 模拟回复并更新冷却

### 3.10 独立项目脚手架
本轮新增文件：
- `bot.py`
- `pyproject.toml`
- `.env.example`

已完成：
- 提供最小 NoneBot 独立启动入口
- 启动时从根目录 `.env` 读取配置
- 注册 OneBot v11 adapter
- 自动加载 `src/plugins` 下插件
- 不在代码中写死 token/key
- 保持依赖简单，仅补齐 `nonebot2 / onebot adapter / openai / python-dotenv`

### 3.11 离线 mock 测试脚本
文件：`tests/mock_pipeline_test.py`

已完成：
- 在运行时动态注入最小 `nonebot` / `nonebot.adapters.onebot.v11` stub 模块
- 覆盖基础判定与入库链路
- 覆盖 dry_run 主链路
- 覆盖最近窗口内多个 bot 消息触发 SKIP 与群级冷却
- 覆盖普通人 `@bot` 不被误杀
- 覆盖私聊不受 bot loop 影响
- 通过 `importlib` 直接加载核心模块，避免触发真实插件启动
- 使用 FakeEvent / FakeBot / Seg 模拟事件、Bot 与消息段
- 已覆盖以下关键场景：
  1. 私聊消息应触发回复判定
  2. 群聊非 @bot 消息应静默入库
  3. 群聊 quote bot 但不 @：应 SKIP 且仍入库
  4. 群聊 quote bot 且 @bot：允许回复
  5. 群聊 quote 普通人但不 @：仍应 SKIP
  6. owner 强制指令不被 quote 规则拦截
  7. dry_run 模式应跳过真实模型与真实发送
  8. bot loop 防护基础行为应可触发

---

## 4. 本轮联调说明补充
本轮已在 `README.md` 中补充：
- 安装依赖方式
- `cp .env.example .env`
- 使用 `YANGYANG_DRY_RUN=1` 启动 dry_run
- `python3 bot.py` 启动 NoneBot
- 对接 OneBot v11 的基本要求
- 在测试群内通过 `@bot` 验证最小闭环
- 当前 MVP 红线：**不主动水群、不接管 AstrBot 生产**

---

## 5. 检查策略
要求执行：
```bash
python3 scripts/check_project.py
```

当前检查策略：
- 若环境缺少 nonebot，不强行启动真实 bot
- 只做语法编译与离线 mock 检查
- 不做超过 5 分钟的真实联机启动
- 本轮检查需覆盖 quote/reply 规则与 dry_run 不回归

---

## 6. 下一步建议
下一步按优先级建议：
1. 验证真实 NoneBot + OneBot v11 本地联调是否可收发
2. 根据实际协议端补齐 `.env` 字段命名与 README 示例
3. 如发现插件路径或导入边界问题，再做最小修复
4. 在保持红线不变前提下，补日志与联调可观测性


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


- OwnerAction Reply Draft MVP：已新增 `owner_action_reply_draft` 草稿层；当前只生成待发送草稿与 dry_run 摘要可见，不真实发送，`real_send` 仍恒为 `False`。


## 本轮补充：Host-side NoneBot Install Prep MVP

已完成：
- 新增宿主机安装文档：`docs/host_nonebot_install.md`
  - 明确当前 Docker / AstrBot 工具环境不建议作为真实 NoneBot 安装环境
  - 给出宿主机 / 裸机 Ubuntu 推荐安装流程
  - 标注 Python 3.11 / 3.12 均可，当前项目已在 3.12 compile 通过
  - 约定使用项目内 `.venv`
  - 提供 `.env.example -> .env`、安装命令、runtime ready check、systemd、日志与权限建议
  - OneBot / NapCat / Lagrange 仅保留占位说明，不写真实 token
- 新增宿主机安装脚本：`scripts/host_setup_nonebot_env.sh`
  - `set -euo pipefail`
  - 支持 `--dry-run` / `--python PATH` / `--skip-check`
  - 仅创建 `.venv`、升级 pip、安装 `-e ".[nonebot]"`、执行只读 ready check
  - 不启动 bot，不连接 OneBot，不修改 `.env`
  - 安装后即使 ready check FAIL，也会展示结果与退出码供宿主机排障
- 新增 systemd 模板：`deploy/systemd/yangyang-nonebot.service.example`
  - 固定示例路径 `/opt/yangyang_nonebot_mvp`
  - 使用 `.env` 作为 `EnvironmentFile`
  - `Restart=on-failure`
  - 不含真实 token
- 新增宿主机只读预检脚本：`scripts/host_preflight_check.sh`
  - 检查疑似 Docker/container
  - 检查 `python3` / `pip` / `git`
  - 检查项目根、`.venv`、`.env`
  - 给出端口与 OneBot 配置提示
  - 不安装、不启动、不发送
- 更新 `README.md`
  - 新增 “Host-side NoneBot Install” 入口
  - 明确当前容器里不建议安装 NoneBot
  - 补最短执行命令与文档链接
- 新增测试：`tests/test_host_install_prep_files.py`
  - 覆盖文档/脚本存在
  - 覆盖 `bash -n`
  - 覆盖 systemd 模板关键字段
  - 覆盖 README 入口
  - 覆盖无真实 token/secret 明文泄露

## 本轮补充：Host Deploy Checklist + README Tightening MVP

已完成：
- 新增宿主机部署清单：`deploy/host_deploy_checklist.md`
  - 覆盖前置原则、宿主机准备、预检、venv 安装、`.env`、OneBot 对接占位、systemd、首次真实 smoke、回滚排障
  - 只整理命令与注意事项，不在当前容器执行
  - 强调真实运行在宿主机 / 旧笔记本 Ubuntu，当前容器只用于开发 / 单测 / mock
- 收紧 `README.md` 表述
  - 新增 checklist 入口
  - 明确 `pip install -e ".[nonebot]"` 应在宿主机项目目录 `.venv` 中执行
  - 强调当前 Docker / AstrBot 环境只用于开发、单测、mock rehearsal、只读检查
  - 重申当前 AstrBot/API 窗口不能替代真实 NoneBot runtime 的 `bot/event`
- 更新 `docs/host_nonebot_install.md`
  - 新增 checklist 链接
  - 补充“本文命令默认在宿主机项目目录执行，不是在当前 AstrBot 容器执行”
- 更新 `docs/current_session_smoke_example.md`
  - 新增 checklist 链接
  - 强调真实 smoke 必须等 NoneBot runtime 与 OneBot 已连接后再做
- 新增测试：`tests/test_host_deploy_checklist_docs.py`
  - 覆盖 checklist 文件存在、关键章节/命令、README 与 docs 链接、无真实 token/secret 泄露、README 中 `pip install -e` 的宿主机/venv 语境
