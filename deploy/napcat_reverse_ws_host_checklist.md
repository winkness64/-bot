# NapCat Reverse WS Host Checklist

> 适用于 **宿主机 / 旧笔记本 Ubuntu 裸机运行 NoneBot**，并由 **NapCat 通过 OneBot v11 反向 WebSocket 主动连接 NoneBot** 的落地场景。
> 当前 **Docker / AstrBot 开发容器只用于开发、mock、只读检查**，**不用于真实连接**。
> “**娅娅笔记本**”可以作为最终运行环境和调试协作环境。

## 1. 适用场景

本清单只处理以下范围：
- 宿主机 / 旧笔记本 Ubuntu 裸机运行 NoneBot；
- NapCat 通过 OneBot v11 **反向 WebSocket** 主动连接 NoneBot；
- 当前 Docker / AstrBot 开发容器只用于开发和 mock，不用于真实连接；
- 娅娅笔记本可作为最终运行环境和后续协作调试环境。

本清单**不做**：
- 不安装依赖；
- 不启动 bot；
- 不连接 NapCat / OneBot；
- 不发送消息；
- 不写真实 token / secret / api key。

## 2. 推荐拓扑

### 2.1 同机部署

如果 NoneBot 和 NapCat 都在同一台笔记本：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

这是首选拓扑，优点：
- 最少网络变量；
- `127.0.0.1` 只在本机回环；
- 端口、防火墙、路由问题最少；
- 部署到娅娅笔记本时，**优先按同机拓扑排查**。

### 2.2 分机部署

如果 NapCat 在另一台机器，而 NoneBot 在宿主机 / 娅娅笔记本：

```text
ws://192.168.x.x:8080/onebot/v11/ws
```

关键提醒：
- `127.0.0.1` 永远指向“当前机器自己”；
- 分机部署时，NapCat 侧 **必须改成 NoneBot 宿主机的局域网 IP**；
- 推荐只走内网 / VPN；
- **不建议公网暴露**。

## 3. 启动顺序

建议固定顺序，不要乱序折腾：

1. 准备 `.env`；
2. 运行 `check_napcat_onebot_config.py`；
3. 启动 NoneBot，让它先监听；
4. 再启动或重连 NapCat；
5. 打开 audit tail-follow；
6. 最后做 current-session smoke；
7. 测完立即 disable。

参考命令顺序：

```bash
cp .env.example .env
.venv/bin/python scripts/check_napcat_onebot_config.py
# 然后再启动 NoneBot runtime
python3 scripts/inspect_owner_action_audit.py --tail-follow
# QQ 当前测试会话：/yy-smoke-current 回应小维
python3 scripts/toggle_current_session_smoke.py --disable --yes
```

如果需要显式保留 disable 回滚命令，最终以：

```bash
python3 scripts/toggle_current_session_smoke.py --disable --yes
```

或：

```bash
toggle_current_session_smoke.py --disable --yes
```

## 4. 端口与监听

推荐示例：
- `HOST=127.0.0.1`
- `PORT=8080`

### 同机部署

同机时通常使用：

```dotenv
HOST=127.0.0.1
PORT=8080
```

适合本机 NapCat 直接回连，风险最低。

### 分机 / 局域网访问

如果 NapCat 不在同机，或确实需要局域网访问，可能需要：

```dotenv
HOST=0.0.0.0
PORT=8080
```

提醒：
- `HOST=0.0.0.0` 只是让服务监听所有网卡；
- 这会引入防火墙与误暴露风险；
- 必须同步检查 `ufw` / 路由 / 局域网访问范围；
- **不要直接暴露到公网**。

如果修改了端口，例如不是 `8080`，NapCat 侧 URL 必须同步改掉。

## 5. URL path

推荐 path：

```text
/onebot/v11/ws
```

完整推荐 URL：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

常见问题：
- path 写错会导致 NapCat 连不上；
- 有时会表现为 404；
- 也可能表现为握手成功但事件不进来。

检查方式：
- 对照 NapCat 侧配置；
- 对照 NoneBot adapter / OneBot adapter 文档；
- 确认 URL 与最终监听 path 一致。

## 6. token / secret

必须关注：
- `ONEBOT_ACCESS_TOKEN` 与 NapCat access token **必须一致**；
- `ONEBOT_SECRET` 如接线方案使用，也要两边一致；
- 空 token 只适合本机短时测试；
- **不建议长期空 token 运行**。

安全要求：
- 不提交仓库；
- 不贴群；
- 不写日志；
- 不复用 AstrBot 的 token / env；
- 不在 README、测试文件、截图里放真实值。

## 7. 防火墙与网络

### 同机

- 一般无需开放端口到局域网；
- `127.0.0.1` 通常就够了；
- 风险最小。

### 分机

分机时至少检查：
- `ufw` / 系统防火墙；
- 宿主机 IP 是否写对；
- 路由 / 子网是否互通；
- `HOST` 是否只监听本地；
- NapCat 那台机器能否访问宿主机端口。

总原则：
- 只走内网；
- 不要暴露到公网。

## 8. 日志判断

正常情况下，NoneBot 日志中应该能看到：
- OneBot adapter 相关加载信息；
- websocket / ws 连接相关信息；
- 连接建立、断开、重连之类提示。

NapCat 日志中应该能看到类似：
- reverse ws connected；
- reverse ws reconnected；
- 鉴权成功或失败；
- URL / 端口 / path 相关报错。

如果看不到连接成功迹象，按这个顺序排查：
1. 端口；
2. URL；
3. token；
4. HOST；
5. 防火墙。

## 9. 娅娅笔记本部署注意事项

已知背景：
- 娅娅的 AstrBot 已经在宿主机裸跑；
- 她有完整系统权限；
- 后续可以协助调试。

但落地时仍建议：
- **不要让 NoneBot 默认长期 root 运行**；
- 优先用专用用户，或使用 `systemd` service 用户；
- 如确需完整系统权限，再逐项授予，不要一步到位常驻 root；
- 避免和 AstrBot 的端口、日志目录、数据目录冲突；
- 不要直接复用 AstrBot 的 token / env；
- 项目目录、日志目录、备份目录要分清楚。

推荐：
- service name 使用 `yangyang-nonebot.service`；
- systemd 日志用 `journalctl` 观察；
- 审计日志保留在项目自己的 `logs/`；
- 备份目录和运行目录单独管理。

建议最少区分：
- 项目目录：例如 `/opt/yangyang_nonebot_mvp`
- 日志目录：例如项目内 `logs/`
- 配置备份目录：例如 `backups/runtime_config/`

## 10. 故障排查矩阵

| 现象 | 可能原因 | 优先排查 |
| --- | --- | --- |
| NapCat 显示连接失败 | NoneBot 未启动 / 端口不对 / HOST 不可达 / path 错 | 先看 NoneBot 是否已监听，再看 URL 与 path |
| 连接后收不到消息 | adapter 未注册 / 权限或账号事件设置问题 / 插件未加载 | 看 `bot.py` 注册、插件加载、账号事件设置 |
| 401 / 鉴权失败 | token 不一致 | 对照 `ONEBOT_ACCESS_TOKEN` 与 NapCat access token |
| 同机可用，分机不可用 | `127.0.0.1` 指向错机器 / 防火墙 / HOST 只监听本地 | 改局域网 IP，检查 `HOST=0.0.0.0` 与防火墙 |
| smoke 不响应 | 未 toggle enable / 不是 owner / 没前缀 / 当前窗口不是 NoneBot runtime / smoke 已 disable | 检查 owner、前缀、链路、是否已 disable |

## 11. 推荐落地检查清单

执行前确认：
- 已复制 `.env.example` 到 `.env`；
- 已确认同机还是分机；
- 已明确 URL、端口、path、token；
- 已确认不走公网；
- 已确认不会与 AstrBot 端口 / 日志 / 数据目录冲突。

执行顺序：
- `.venv/bin/python scripts/check_napcat_onebot_config.py`
- 启动 NoneBot
- 启动 / 重连 NapCat
- `python3 scripts/inspect_owner_action_audit.py --tail-follow`
- QQ 当前测试会话发送：`/yy-smoke-current 回应小维`
- 测完执行：`python3 scripts/toggle_current_session_smoke.py --disable --yes`

## 12. 关联文档

- `docs/napcat_onebot_setup.md`
- `docs/host_nonebot_install.md`
- `deploy/host_deploy_checklist.md`
- `deploy/systemd/yangyang-nonebot.service.example`
