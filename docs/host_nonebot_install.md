# Host-side NoneBot Install

部署清单另见：`deploy/host_deploy_checklist.md`

## 为什么不建议在当前 Docker / AstrBot 工具环境里安装

本文命令默认在**宿主机项目目录**执行，不是在当前 AstrBot / Docker 容器执行。

当前开发工具环境是容器/受限环境，只适合：
- 写代码
- 跑只读检查
- 跑离线测试

不适合作为最终 NoneBot 运行环境，原因包括：
- 容器里的系统权限、设备权限、网络环境与最终宿主机不一致
- 当前环境不是你后续真正要长期运行 QQ / OneBot / NoneBot 的位置
- 在这里执行 `pip install`、创建 venv、联机接 OneBot，不能代表宿主机/裸机实际情况
- 当前项目后续明确希望 bot 拥有更完整的系统权限，因此更适合在宿主机或旧笔记本 Ubuntu 上部署

结论：**当前容器只做开发和检查，不建议在这里安装 NoneBot 运行依赖。**

## 推荐运行环境

推荐：
- Ubuntu 宿主机 / 裸机 / 旧笔记本
- Python `3.11` 或 `3.12`
- 当前项目代码已在 `3.12` 做过 compile 通过

建议：
- 项目目录内使用 `.venv`
- 不默认用 root 运行
- 先使用专用用户运行 bot
- 只有确实需要完整系统操作时，再按需授予 `sudo` 或特定 system group 权限

## 推荐目录

示例：

```bash
/opt/yangyang_nonebot_mvp
```

你也可以放在自己的工作目录，只要后续 `systemd` 模板里的路径与实际一致即可。

## 宿主机安装流程

先把项目同步到宿主机，然后进入项目根目录：

```bash
cd /opt/yangyang_nonebot_mvp
```

建议先跑只读预检：

```bash
bash scripts/host_preflight_check.sh
```

再看安装脚本将执行什么：

```bash
bash scripts/host_setup_nonebot_env.sh --dry-run
```

确认无误后，再执行真实安装：

```bash
bash scripts/host_setup_nonebot_env.sh
```

等价手工命令如下：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[nonebot]"
```

说明：
- 使用项目内 `.venv`
- 只安装依赖
- **不启动 bot**
- **不连接 OneBot**
- **不发送消息**
- **不修改 `.env`**

如果宿主机需要指定 Python，可用：

```bash
bash scripts/host_setup_nonebot_env.sh --python /usr/bin/python3.12
```

## 安装后检查

安装完成后运行：

```bash
.venv/bin/python scripts/check_nonebot_runtime_ready.py
```

这个脚本只做只读检查：
- 不启动 bot
- 不连接 OneBot
- 不发送消息
- 若存在 `.env`，只打印 key，不打印 value

## `.env` 配置

先复制模板：

```bash
cp .env.example .env
```

然后按宿主机实际情况填写。

注意：
- 不要提交真实 token、secret、API key
- `ONEBOT_ACCESS_TOKEN`、`ONEBOT_SECRET`、模型 API key 都只在宿主机本地填写
- 本文档不提供真实凭据示例

## OneBot / NapCat / Lagrange 连接说明

这里只放占位和注意事项，不填真实 token：

- NapCat / Lagrange / 其他 OneBot v11 实现均可
- 你需要自行确认：
  - HTTP / WS / 反向 WS 采用哪一种模式
  - NoneBot 监听地址与协议端地址是否一致
  - access token / secret 是否一致
  - 协议端是否已经登录并稳定在线
- 请把真实连接参数写入宿主机上的 `.env`
- 不要把真实 token 写进仓库、文档或测试文件

## systemd 部署方式

项目已提供模板：

- `deploy/systemd/yangyang-nonebot.service.example`

典型流程：

```bash
sudo cp deploy/systemd/yangyang-nonebot.service.example /etc/systemd/system/yangyang-nonebot.service
sudo systemctl daemon-reload
sudo systemctl enable yangyang-nonebot.service
sudo systemctl start yangyang-nonebot.service
sudo systemctl status yangyang-nonebot.service
```

使用前请至少检查：
- `WorkingDirectory`
- `ExecStart`
- `EnvironmentFile`
- `User` / `Group`

## 日志位置建议

推荐至少区分两类日志：
- `journalctl -u yangyang-nonebot.service`
- 项目内业务日志目录，例如：`/opt/yangyang_nonebot_mvp/logs/`

建议：
- 审计/投递类 JSONL 继续放项目内 `logs/`
- systemd stdout/stderr 通过 `journalctl` 看
- 如后续日志量较大，再补 logrotate

## 权限建议

如果后续 bot 需要较完整系统权限，可以运行在宿主机/裸机上；但仍建议遵循最小权限原则：

1. 先用专用用户运行
2. 先不给 `root`
3. 只有明确需要时，再补：
   - `sudo`
   - 串口/音频/视频/docker 等特定 system group
   - 特定目录读写权限

不建议默认直接 `root` 启动。

## 最短执行路径

```bash
bash scripts/host_preflight_check.sh
bash scripts/host_setup_nonebot_env.sh --dry-run
bash scripts/host_setup_nonebot_env.sh
.venv/bin/python scripts/check_nonebot_runtime_ready.py
```
