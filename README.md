# YangYang NoneBot Framework

秧秧当前使用的 NoneBot 工程主线。

这已经不是最早那版 **MVP 第一阶段试验壳**，而是一条围绕 **owner 私聊控制、可控执行、安全边界、流式稳定性、运维可追踪** 持续收口过的框架线。

> 当前重点不是“花哨多代理表演”，而是 **可控、可验、可维护、可继续开发**。

---

## 这项目现在是什么

这是一个基于 NoneBot2 + OneBot v11 的工程化聊天/控制框架，主打：

- owner 私聊高优先级控制链路
- 群聊/私聊消息接入与上下文装配
- 可配置模型路由与 fallback 行为
- 受控 sender / owner action 执行闸门
- 会话状态压缩、提示构造、记忆注入
- dry_run / mock rehearsal / 回归测试 / 运维检查工具链

简单说：

**它现在更像一个可维护的主脑框架，而不是早期验证想法的 MVP 壳子。** oh~卖♂萧的。

---

## 当前定位

这条主线目前服务于以下目标：

1. **把 owner 私聊做成真正稳定的控制台**
2. **把回复链路做成可观测、可回滚、可验证的工程系统**
3. **把自动化能力限制在可控边界内，不玩失控工厂**
4. **把近期有效框架工作沉淀成可继续演进的稳定检查点**

---

## 当前已经稳定落地的能力

### 1. 消息接入与基础主链
- OneBot v11 群聊 / 私聊事件适配
- SQLite 消息入库
- 最近上下文读取与主链拼装
- 群聊静默规则 / owner 放行规则 / 基础冷却控制

### 2. Owner 控制链路
- owner 指令解析与轻量结构化挂载
- owner action gate 权限总闸与分权限开关
- current-session reply 投递判定链路
- dry_run 下可见 action / gate / context / delivery 摘要
- 默认仍以安全为先：**不开闸不真发**

### 3. 会话状态与提示构造
- owner 私聊 session-state 压缩 V1
- 长对话 rolling summary 回填
- prompt 走 `rolling_summary + limited recent history`
- suspend / resume / diff hints 已接入控制流

### 4. 模型与 fallback
- OpenAI 兼容路由接口
- 主模型失败后的 fallback 连续性保留
- safety fallback 与敏感原文隔离
- dry_run 固定模拟回复能力

### 5. 流式与发送稳定性
- send_stream SSE 断连感知
- finished / cancel / cleanup 行为补强
- sender adapter 抽象已接好
- 默认 NullSenderAdapter 安全兜底，避免误发

### 6. 工具链与运维侧
- `check_project` 等基础巡检脚本
- current-session smoke rehearsal
- host 侧部署 / preflight / handoff 文档
- 工单、发布说明、补丁说明持续留档

---

## 当前明确的工程判断

### 不是继续堆“黑奴工厂”
最近这一轮已经很明确：

- 自动工厂汇报线已从活跃调度路径移除
- 老 notifier 的分钟级 dedup/skip 噪声已收口
- 工厂相关资产先降级为 **人工探路 / 草稿 / 试验能力**

原因很直接：

**我们要的是可控 BOY，不是在线黑箱。**

能看到它活着没用，得知道它：
- 接了什么任务
- 为什么这么判断
- 输出靠不靠谱
- 有没有跑偏

所以当前框架路线更偏向：

> **少量、可控、共享上下文、结构化回报的特种作战单元**，而不是看起来热闹的工厂戏法。ass♂we♂can。

---

## 当前仓库怎么用

## 1）开发 / 单测 / mock rehearsal
适用：当前开发容器、日常改代码、自检回归。

常用命令：

```bash
python3 scripts/check_project.py
python3 scripts/check_napcat_onebot_config.py
python3 scripts/run_current_session_smoke_rehearsal.py
python3 scripts/run_current_session_smoke_rehearsal.py --mock-send
pytest -q
```

这里适合：
- 跑测试
- 改逻辑
- 看 dry_run 输出
- 做只读核对

这里**不等于真实 NoneBot runtime 现场**。

---

## 2）宿主机部署 / 真实运行环境
适用：真实 NoneBot + OneBot 联调、部署、运行巡检。

先看这些文档：

- `docs/host_nonebot_install.md`
- `deploy/host_deploy_checklist.md`
- `docs/napcat_onebot_setup.md`
- `deploy/napcat_reverse_ws_host_checklist.md`
- `docs/host_handoff_package.md`

常用命令：

```bash
bash scripts/host_preflight_check.sh
bash scripts/host_setup_nonebot_env.sh --dry-run
bash scripts/host_setup_nonebot_env.sh
.venv/bin/python scripts/check_napcat_onebot_config.py
.venv/bin/python scripts/check_nonebot_runtime_ready.py
```

---

## 3）current-session smoke
前提：
- NoneBot 已启动
- OneBot / NapCat / Lagrange 已连接
- 审计链路已开
- smoke toggle 已启用

文档：
- `docs/current_session_smoke_example.md`

常用命令：

```bash
.venv/bin/python scripts/toggle_current_session_smoke.py --enable --yes
.venv/bin/python scripts/check_current_session_smoke_ready.py
.venv/bin/python scripts/run_current_session_smoke_rehearsal.py --mock-send
.venv/bin/python scripts/inspect_owner_action_audit.py --tail-follow
```

测试会话示例：

```text
/yy-smoke-current 回应小维
```

注意：
- 普通“回应小维”不会自动触发真实 smoke
- 测完要及时 disable

---

## 安全边界

当前 README 先把边界说死，避免误会：

- AstrBot/API 窗口 **不能替代** 真实 NoneBot runtime 的 `bot/event`
- owner action 默认 **解析可见，但不自动真发**
- 跨群 `send_group_message` 仍保持严格锁定
- 真实执行必须经过显式配置、权限开闸与 sender 注入
- 不因为“能跑”就放开危险路径

一句话：

**默认保守，显式开闸，链路留痕。**

---

## 最近这轮有价值的框架更新

### Owner 私聊 session-state compression V1
- 长私聊历史支持 compact rolling summary backfill
- prompt 优先走摘要 + 近期消息
- 支持 suspend / resume / diff hints

### Factory 自动汇报线收口
- deprecated notifier 已移出 active scheduler boot path
- 老 dedup/skip 噪声不再每分钟刷屏
- 工厂资产保留为手动探路能力

### SSE send_stream guardrails
- 增加断连感知
- 收紧 finished-state / enqueue / cancellation
- 降低半死不活的 teardown 风险

### Fallback 行为验证
- 普通 fallback 保留连续性
- safety fallback 持续隔离敏感原文

### 运维与留档
- 工单说明、发布说明、补丁说明持续补齐
- 当前主线已有稳定检查点可追

---

## 验证快照

近期主线验证结果：

- owner 私聊 prompt / session-state 定向回归：`50 passed`
- factory notifier + session-state + prompt-context 回归包：`54 passed`
- 本轮主线同步验证快照：`68 passed`

---

## Git / 交付锚点

- 主线同步提交：`e102600`
- 稳定检查点 tag：`framework-sync-20260619`

这轮交付的意义不是新功能狂飙，
而是把最近真正有用的框架工作，焊成了一个 **可追踪、可回滚、可继续开发** 的稳态落点。

---

## 文档入口

建议优先看：

- `docs/README_FRAMEWORK_SYNC_RELEASE_NOTE_20260619.md`
- `current_task.md`
- `current_task_result.md`
- `PROJECT_PROGRESS.md`
- `PATCH_NOTES_send_stream_sse_guardrails.md`

如果你是来接手、回溯或继续开发，这几份足够快速上手主线状态。

---

## 旧版 README 保留说明

老版本 README 没删，已作为历史门面保留：

- `README_MVP_LEGACY_20260619.md`

需要对照早期口径、看最初 MVP 说明，直接翻这份就行。

---

## 一句话总结

**这个仓库现在卖的不是“多代理 PPT”，而是一条能继续长、能继续修、能继续打仗的 NoneBot 工程主线。**

done。♂爽。
