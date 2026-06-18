# Host Deploy Checklist

> 本清单只整理 **宿主机 / 旧笔记本 Ubuntu** 上从零到首次真实 smoke 前后的执行顺序。
> **只写命令与注意事项，不在当前 AstrBot / Docker 容器内执行。**

## A. 前置原则

- **不要在当前 AstrBot Docker / 容器里跑 NoneBot。**
- 当前容器只用于：开发、单测、mock rehearsal、只读检查。
- 真实运行位置是：宿主机 / 旧笔记本 Ubuntu。
- 建议使用专用用户运行，不默认 root。
- 如确需更完整系统权限，再逐项授予 sudo / system group，不要一上来全开。
- 当前 AstrBot/API 聊天窗口不能替代真实 NoneBot runtime 的 `bot/event`。

## B. 宿主机准备

示例目录：

```bash
sudo mkdir -p /opt/yangyang_nonebot_mvp
sudo chown -R "$USER":"$USER" /opt/yangyang_nonebot_mvp
cd /opt/yangyang_nonebot_mvp
```

安装常见系统依赖：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git build-essential ca-certificates
```

项目复制 / 拉取方式占位：

```bash
# 方式1：git clone <your-repo-url> /opt/yangyang_nonebot_mvp
# 方式2：rsync / scp / 局域网同步到宿主机
# 方式3：先在开发环境生成交接包，再通过宝塔下载到宿主机
#   参考：docs/host_handoff_package.md
#   示例：bash scripts/build_host_handoff_package.sh
cd /opt/yangyang_nonebot_mvp
```

注意事项：
- 后续所有命令默认在 **宿主机项目根目录** 执行。
- 如走交接包方式，先看 `docs/host_handoff_package.md`。
- 可以先在开发环境生成交接包，再**通过宝塔下载交接包**到宿主机。
- 不在当前容器里创建 `.venv`。
- 不在当前容器里安装 NoneBot 依赖。

## C. 预检

```bash
bash scripts/host_preflight_check.sh
```

WARN 处理方式：
- `Detected /.dockerenv` / container marker：说明你还在容器里，切回宿主机再做。
- `.venv does not exist yet`：首次部署前正常，继续下一步。
- `.env missing`：首次部署前正常，后面复制 `.env.example` 再填。
- `python3/git/pip not found`：先在宿主机补装系统包再继续。
- 预检是只读提示；先把 WARN 逐条看懂，不要硬跳过宿主机场景差异。

## D. 创建 venv 与安装 NoneBot

先看脚本将执行什么：

```bash
bash scripts/host_setup_nonebot_env.sh --dry-run
```

确认无误后再执行：

```bash
bash scripts/host_setup_nonebot_env.sh
```

安装后先做 NapCat / OneBot 配置检查，再做 runtime 接线检查：

```bash
.venv/bin/python scripts/check_napcat_onebot_config.py
.venv/bin/python scripts/check_nonebot_runtime_ready.py
```

注意事项：
- `pip install -e "[nonebot]"` 相关动作应在 **宿主机项目目录的 `.venv`** 中完成。
- 先阅读 `docs/napcat_onebot_setup.md`，按反向 WebSocket 推荐模式整理 `.env`。
- OneBot / NapCat 宿主机落地检查同时参考 `deploy/napcat_reverse_ws_host_checklist.md`。
- 通过 `.venv/bin/python scripts/check_napcat_onebot_config.py` 后，再继续启动 NoneBot。
- 本阶段不要在当前 AstrBot 容器执行真实安装。
- 该流程不启动 bot、不连接 OneBot、不发送消息。

## E. `.env` 准备

```bash
cp .env.example .env
```

只填写宿主机本地需要的 key，不写真实值到文档：
- `DRIVER`
- `HOST`
- `PORT`
- `ONEBOT_WS_URL`
- `ONEBOT_WS_REVERSE_URL`
- `ONEBOT_API_ROOT`
- `ONEBOT_ACCESS_TOKEN`
- `ONEBOT_SECRET`
- 模型 API key（如 `OPENAI_API_KEY` / `DEEPSEEK_API_KEY`）

注意事项：
- token / secret / API key 不提交仓库。
- 不把真实值贴到群里。
- 不把真实值写进测试文件或 README。

## F. OneBot / NapCat / Lagrange 对接占位

先看文档：
- `docs/napcat_onebot_setup.md`
- `deploy/napcat_reverse_ws_host_checklist.md`

部署前先确认：
- 使用正向 WebSocket、反向 WebSocket，还是其他模式。
- NoneBot 侧的 `host` / `port`。
- OneBot 侧的监听地址、端口、access token。
- NapCat / Lagrange 是否已登录且稳定在线。
- 当前阶段先只连 **测试号 / 测试群**。

注意事项：
- 这里只确认参数类型，不在文档里填真实值。
- 参数不明确时，不要急着开跨群或更大范围测试。

### 娅娅笔记本部署入口

如果最终部署到娅娅笔记本：
- 优先按同机拓扑检查；
- 不要默认长期 root 运行；
- 注意与 AstrBot 的端口、日志目录、数据目录冲突；
- 详细见 `deploy/napcat_reverse_ws_host_checklist.md`。

## G. systemd 部署

复制模板：

```bash
sudo cp deploy/systemd/yangyang-nonebot.service.example /etc/systemd/system/yangyang-nonebot.service
```

按宿主机实际情况修改以下字段：
- `WorkingDirectory`
- `ExecStart`
- `EnvironmentFile`
- `User`
- `Group`

加载与启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable yangyang-nonebot.service
sudo systemctl start yangyang-nonebot.service
sudo systemctl status yangyang-nonebot.service
```

查看日志：

```bash
sudo journalctl -u yangyang-nonebot.service -n 100 --no-pager
sudo journalctl -u yangyang-nonebot.service -f
```

注意事项：
- 先确认 `.env`、路径、用户权限都正确，再启动。
- 不要把 service 模板里的示例路径原样照抄成错误路径。

## H. 首次真实 smoke 流程

先做只读检查：

```bash
.venv/bin/python scripts/check_napcat_onebot_config.py
.venv/bin/python scripts/check_nonebot_runtime_ready.py
python3 scripts/toggle_current_session_smoke.py --enable --yes
python3 scripts/check_current_session_smoke_ready.py
python3 scripts/run_current_session_smoke_rehearsal.py --mock-send
```

然后启动并确认真实链路：
- 启动 / 确认 NoneBot runtime 已运行。
- 确认与 OneBot 已连接。
- 确认只在测试号 / 测试群 / 当前测试会话内操作。

开只读审计观察：

```bash
python3 scripts/inspect_owner_action_audit.py --tail-follow
```

在 QQ 当前测试会话发：

```text
/yy-smoke-current 回应小维
```

无论成功还是失败，立即关闭 smoke：

```bash
python3 scripts/toggle_current_session_smoke.py --disable --yes
```

注意事项：
- 真实 smoke 必须等 NoneBot runtime 与 OneBot 已连接后再做。
- `--mock-send` 只是本地 mock 彩排，不是真实 QQ 发消息。
- 普通 `回应小维` 不等于真实 smoke；要走带前缀命令。

## I. 回滚与故障处理

先关 smoke：

```bash
python3 scripts/toggle_current_session_smoke.py --disable --yes
```

停止服务：

```bash
sudo systemctl stop yangyang-nonebot.service
sudo systemctl status yangyang-nonebot.service
```

查看审计与 systemd 日志：

```bash
python3 scripts/inspect_owner_action_audit.py --limit 50
sudo journalctl -u yangyang-nonebot.service -n 200 --no-pager
```

注意事项：
- 不要删备份配置。
- 不要在配置不明时开放跨群。
- 先看 audit / journal / ready check 输出，再决定下一步。
