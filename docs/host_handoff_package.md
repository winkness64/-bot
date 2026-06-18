# Host Handoff Release Package

本文只处理一件事：**在当前开发环境生成一个可交给宿主机 / 娅娅笔记本测试的安全交接压缩包**。

边界：
- 只打包源码、脚本、文档、配置模板、测试；
- **不安装依赖**；
- **不创建当前容器 `.venv`**；
- **不启动 bot**；
- **不连接 NapCat / OneBot**；
- **不发送消息**；
- **不随包提供 `.env`**；
- **不写入、不打印真实 token / secret / api key**。

## 1. 用途

适用场景：
- 当前仍在开发容器内整理 MVP 项目；
- 需要把项目打成压缩包；
- 通过宝塔下载到“娅娅住的笔记本”或其他宿主机；
- 让宿主机在裸跑环境中继续预检、补 `.env`、安装依赖、对接 NapCat / OneBot、做后续测试。

## 2. 生成交接包

项目根目录执行：

```bash
bash scripts/build_host_handoff_package.sh --dry-run
bash scripts/build_host_handoff_package.sh
```

可选参数：

```bash
bash scripts/build_host_handoff_package.sh --check-only
bash scripts/build_host_handoff_package.sh --no-tests
bash scripts/build_host_handoff_package.sh --output-dir dist/release
bash scripts/build_host_handoff_package.sh --name yaya_host_handoff_test
```

默认行为：
- 输出目录：`dist/`
- 包名格式：`yangyang_nonebot_mvp_host_handoff_YYYYMMDD-HHMMSS.tar.gz`
- 同时生成：
  - `*.MANIFEST.txt`
  - `*.sha256`
- 默认**包含** `tests/`

## 3. 包内默认包含什么

默认包含：
- `bot.py`
- `src/`
- `scripts/`
- `README.md`
- `docs/`
- `deploy/`
- `.env.example`
- `pyproject.toml`
- `PROJECT_PROGRESS.md`
- `tests/`（默认包含）

## 4. 默认排除什么

默认排除：
- `.env`
- `.venv/`
- `venv/`
- `__pycache__/`
- `.pytest_cache/`
- `.git/`
- `logs/`
- `dist/`
- 任意路径段 `backups/`
- `src/backups/`
- `src/plugins/yangyang/data/`（运行态 runtime_config、audit、memory、缓存不随交接包提供）
- `src/plugins/yangyang/core/isaac_agent/memory.jsonl`（agent 运行态记忆不随交接包提供）
- `*.db`
- `*.sqlite`
- `*.sqlite3`
- `*.log`
- `*.pyc`
- `*.tmp`
- `*.bak`
- `*.corrupted`
- `*.backup-*`
- `*.before_*`
- 文件名含 `token` / `secret` / `apikey` / `api_key` / `password` 的路径

说明：
- `.env.example` 作为模板会保留；
- 真实 `.env`、真实 token、真实 secret **绝不能随包提供**。

## 5. 脚本自带安全检查

脚本会做两轮检查：

1. **打包前检查**
   - 只检查路径与文件名；
   - 如果发现敏感项会被纳入，直接失败。

2. **打包后检查**
   - 读取 tar 列表生成 manifest；
   - 再次确认其中没有 `.env`、`.venv`、`logs/`、`dist/`、数据库、日志、token/secret/apikey 相关路径；
   - 若发现问题，直接 FAIL，并删除已生成的包与附属文件。

注意：
- 只检查路径和常见文件名；
- **不会扫描或打印真实密钥内容**。

## 6. 通过宝塔下载

生成成功后，去项目目录下的 `dist/` 找产物，例如：

```text
dist/yangyang_nonebot_mvp_host_handoff_20260528-153000.tar.gz
dist/yangyang_nonebot_mvp_host_handoff_20260528-153000.MANIFEST.txt
dist/yangyang_nonebot_mvp_host_handoff_20260528-153000.sha256
```

后续可通过宝塔文件管理：
- 定位到项目 `dist/`；
- 下载 `*.tar.gz`；
- 如需要，也可一并下载 `*.MANIFEST.txt` 与 `*.sha256` 便于核对。

## 7. 在娅娅笔记本解压

宿主机示例目录：

```bash
sudo mkdir -p /opt/yangyang_nonebot_mvp
sudo tar -xzf yangyang_nonebot_mvp_host_handoff_*.tar.gz -C /opt/yangyang_nonebot_mvp
cd /opt/yangyang_nonebot_mvp
```

如果压缩包内是项目根内容，解压后第一步先跑：

```bash
bash scripts/host_preflight_check.sh
```

然后继续按以下文档推进：
- `deploy/host_deploy_checklist.md`
- `deploy/napcat_reverse_ws_host_checklist.md`

## 8. `.env` 处理要求

`.env` 必须在宿主机本地生成：

```bash
cp .env.example .env
```

然后再按宿主机实际情况填写。

强调：
- `.env` **不随压缩包提供**；
- token / secret / api key **不要放进压缩包**；
- 不要把真实值提交仓库、贴群、写进测试文件。

## 9. 后续调试信息回传

如果后续需要让娅娅回传调试信息，可以再补一个 debug bundle 流程。

当前状态：**后续补充**。
