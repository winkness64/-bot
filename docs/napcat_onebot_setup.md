# NapCat / OneBot v11 接入准备

本文只整理 **NapCat / OneBot v11 与 NoneBot 的接线准备**：配置模板、占位说明、只读检查。

边界说明：
- 宿主机 / 旧笔记本落地检查另见：`deploy/napcat_reverse_ws_host_checklist.md`
- **不在当前 AstrBot / Docker 开发容器里真实连接 NapCat / OneBot**
- **不启动 bot**
- **不发送消息**
- **不写真实 token / secret / api key**
- 当前阶段先只连 **测试号 / 测试群**

## 1. 推荐对接模式：优先反向 WebSocket

当前推荐优先使用 **反向 WebSocket（Reverse WebSocket）**：
- **NapCat 主动连接 NoneBot**
- **NoneBot 作为服务端监听本地端口**
- 在 NapCat 侧填写反向 WS URL

推荐原因：
- 宿主机部署时通常更稳定
- NoneBot 作为服务端监听固定本地端口，排查更直观
- NapCat 主动回连更适合宿主机常驻服务场景

典型 URL 占位示例：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

如果部署到娅娅笔记本，优先按**同机拓扑**检查，除非 NapCat 不在同机。

如果 NapCat 与 NoneBot **不在同一台机器**：
- 不要继续写 `127.0.0.1`
- 应改成 **运行 NoneBot 的宿主机局域网 IP**，例如：

```text
ws://192.168.x.x:8080/onebot/v11/ws
```

因为：
- `127.0.0.1` 永远指向“当前这台机器自己”
- NapCat 和 NoneBot 分机部署时，NapCat 看到的 `127.0.0.1` 不是 NoneBot 那台机器

## 2. NapCat 侧配置占位

在 NapCat 面板中，找到类似这些入口：
- OneBot v11
- WebSocket
- 反向 WebSocket / Reverse WS
- Access Token / Secret

按占位填写，**不要写真实值到文档、截图、测试文件**：

- 协议：`OneBot v11`
- 连接模式：`反向 WebSocket`
- 反向 WebSocket URL：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

- access token：

```text
<YOUR_ONEBOT_ACCESS_TOKEN>
```

- secret（如 NapCat / 网关实现支持或要求）：

```text
<YOUR_ONEBOT_SECRET>
```

建议：
- 初次只绑定 **测试 QQ 号 / 测试群**
- 不要直接接生产号、大群、多个群同时压测
- 不要把 access token / secret 贴到群里

## 3. NoneBot `.env` 配置说明

根据当前项目的 `bot.py`：
- 启动入口会 `load_dotenv(ROOT / ".env")`
- 然后 `nonebot.init()`
- 注册 `OneBotV11Adapter`
- 加载 `src/plugins`

所以 `.env` 里应至少准备以下 **真实 NoneBot 生效 key**：

- `DRIVER`
- `HOST`
- `PORT`
- `LOG_LEVEL`
- `ONEBOT_ACCESS_TOKEN`
- `ONEBOT_SECRET`（如接线方案适用）

推荐占位模板：

```dotenv
DRIVER=~fastapi+~httpx+~websockets
HOST=127.0.0.1
PORT=8080
LOG_LEVEL=INFO
ONEBOT_ACCESS_TOKEN=
ONEBOT_SECRET=
```

说明：
- `DRIVER` 这里保留 server driver 能力，便于反向 WS 场景下由 NoneBot 监听端口
- 如果后续实际运行环境对 driver 组合有调整，以 **NoneBot 实际可用 driver** 为准
- 不确定时，至少要保证存在 **FastAPI/server driver 支持反向 WS**

### 文档辅助 / 检查辅助 key

可以额外放一些 **文档辅助 / 检查用途** 的变量，例如：

```dotenv
NAPCAT_CONNECTION_MODE=reverse_ws
NAPCAT_REVERSE_WS_URL=ws://127.0.0.1:8080/onebot/v11/ws
```

注意：
- 这些 `NAPCAT_*` 变量主要用于 **文档提示 / 检查脚本**
- **不一定被 NoneBot 直接读取**
- 真实生效仍以 NoneBot / adapter 实际读取的 key 为准

### 与当前 `.env.example` 的关系

本项目 `.env.example` 里保留了现有 OneBot 相关 key，例如：
- `ONEBOT_WS_URL`
- `ONEBOT_API_ROOT`
- `ONEBOT_WS_REVERSE_URL`
- `ONEBOT_ACCESS_TOKEN`
- `ONEBOT_SECRET`

说明：
- 当前文档以 **反向 WebSocket 优先** 为推荐方案
- 但模板里仍可保留正向 WS / API root 等占位，方便后续切换或排查
- 真实接入时请以 **你最终选择的模式** 为准，不要同时乱填后误判

## 4. 正向 WebSocket：可选备选方案

正向 WebSocket（Forward WS）是：
- **NoneBot 主动连接 NapCat**

这可以作为备选，但默认仍推荐 **反向 WS**。

正向 WS 占位示例：

```text
ws://127.0.0.1:3001/
```

或者在 `.env` 里保留类似占位：

```dotenv
ONEBOT_WS_URL=ws://127.0.0.1:3001/
```

使用正向 WS 时要额外确认：
- NapCat 是否在对应端口提供 WS 服务
- access token 是否与 NoneBot 侧一致
- path 是否与 NapCat 实际配置匹配

## 5. 安全注意

- token / secret / API key **不要提交仓库**
- token / secret **不要贴群、不要发截图、不要写进日志**
- 不要把 NoneBot 监听端口直接暴露到公网
- 首次只连 **测试号 / 测试群**
- smoke 测试完成后，**立即 disable**
- 如果 `HOST=0.0.0.0`，要确认防火墙与公网暴露风险

## 6. 推荐准备顺序

宿主机上建议顺序：

```bash
cp .env.example .env
.venv/bin/python scripts/check_napcat_onebot_config.py
.venv/bin/python scripts/check_nonebot_runtime_ready.py
```

然后再继续：
- 确认 NapCat 侧 URL / token / secret 占位已按宿主机实际填写
- 确认 NoneBot 与 NapCat 在同机还是分机部署
- 确认只连接测试号 / 测试群
- **通过检查后再启动 NoneBot**

## 7. 故障排查

### 7.1 端口不通

检查：
- NoneBot 是否真的监听了你配置的 `HOST:PORT`
- 宿主机本地防火墙是否放行
- 分机部署时局域网互通是否正常

### 7.2 URL path 错误

重点确认：
- 反向 WS URL 是否写成了：

```text
/onebot/v11/ws
```

不同实现 path 可能不同；当前文档和检查脚本只把它当作 **推荐占位 / 常见路径提示**。

### 7.3 token 不一致

检查：
- NapCat 侧 access token
- NoneBot / adapter 读取到的 access token
- 是否有多份 `.env`、systemd `EnvironmentFile` 指向错文件

### 7.4 `127.0.0.1` 指向错机器

如果 NapCat 与 NoneBot 不在同一机器：
- `127.0.0.1` 指向的是 NapCat 自己那台机器
- 应改成 **NoneBot 宿主机局域网 IP**

### 7.5 防火墙

检查：
- Ubuntu `ufw`
- 路由器 / 交换网络隔离
- 云主机安全组（如果以后迁移）

### 7.6 NoneBot 没注册 OneBot v11 adapter

当前项目 `bot.py` 应具备：
- 读取 `.env`
- 注册 `OneBotV11Adapter`
- 加载 `src/plugins`

如果缺少 adapter 注册，NapCat 就算连到端口，也不会按预期处理 OneBot v11 事件。

## 8. 只读检查脚本

当前项目新增只读检查：

```bash
python3 scripts/check_napcat_onebot_config.py
```

宿主机推荐：

```bash
.venv/bin/python scripts/check_napcat_onebot_config.py
```

这个脚本只会：
- 检查 `.env` / `.env.example` / `bot.py` / `pyproject.toml`
- 报告 key 是否存在、格式是否看起来合理
- **不连接网络**
- **不监听端口**
- **不启动 bot**
- **不打印 token value**
