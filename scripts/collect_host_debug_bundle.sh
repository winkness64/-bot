#!/usr/bin/env bash
# ============================================================
# collect_host_debug_bundle.sh
# Phase 4B: 一键收集脱敏调试信息
# 用法: bash scripts/collect_host_debug_bundle.sh
# 输出: /tmp/yangyang_debug_bundle_<timestamp>.txt
# ============================================================
set -e

WORKSPACE="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
OUTFILE="/tmp/yangyang_debug_bundle_${TIMESTAMP}.txt"

{
  echo "========================================="
  echo "秧秧 Debug Bundle — ${TIMESTAMP}"
  echo "========================================="
  echo ""

  # ---- 1. 系统信息 ----
  echo "=============================="
  echo "[1/8] 系统信息"
  echo "=============================="
  echo "Hostname: $(hostname)"
  echo "Kernel: $(uname -r)"
  echo "OS: $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
  echo "Uptime: $(uptime -p)"
  echo "Memory: $(free -h | grep Mem | awk '{print $3 "/" $2}')"
  echo "Disk: $(df -h "$WORKSPACE" | tail -1 | awk '{print $3 "/" $2 " (" $5 ")"}')"
  echo "CPU Load: $(uptime | awk -F'load average:' '{print $2}')"
  echo ""

  # ---- 2. Python / venv ----
  echo "=============================="
  echo "[2/8] Python / venv"
  echo "=============================="
  cd "$WORKSPACE"
  if [ -f ".venv/bin/python" ]; then
    echo "Python: $(".venv/bin/python" --version 2>&1)"
  else
    echo "Python: NOT FOUND (.venv)"
  fi
  echo "Venv Size: $(du -sh .venv 2>/dev/null | awk '{print $1}')"
  echo ""

  # ---- 3. 依赖版本 ----
  echo "=============================="
  echo "[3/8] 关键依赖版本"
  echo "=============================="
  if [ -f ".venv/bin/pip" ]; then
    for pkg in nonebot2 nonebot-adapter-onebot nonebot-plugin-alconna httpx pydantic uvicorn fastapi websockets; do
      ver=$(".venv/bin/pip" show "$pkg" 2>/dev/null | grep "^Version:" | awk '{print $2}')
      echo "  $pkg: ${ver:-<未安装>}"
    done
  fi
  echo ""

  # ---- 4. .env 脱敏摘要 ----
  echo "=============================="
  echo "[4/8] .env 脱敏摘要"
  echo "=============================="
  if [ -f ".env" ]; then
    echo "存在: yes"
    echo "大小: $(wc -c < .env) bytes"
    echo ""
    echo "--- 脱敏内容 ---"
    while IFS='=' read -r key val; do
      # 过滤空行和注释
      [ -z "$key" ] && continue
      [[ "$key" == \#* ]] && continue
      # 判断敏感字段
      case "$key" in
        *KEY*|*TOKEN*|*SECRET*|*PASSWORD*|*ACCESS*|*AUTH*|*API_KEY*|*APISecret*)
          echo "  $key=**** (已脱敏)"
          ;;
        *)
          echo "  $key=$val"
          ;;
      esac
    done < .env
  else
    echo ".env: 不存在"
  fi
  echo ""

  # ---- 5. runtime_config 状态 ----
  echo "=============================="
  echo "[5/8] runtime_config 状态"
  echo "=============================="
  CONFIG_PATH="$WORKSPACE/src/plugins/yangyang/data/runtime_config.json"
  if [ -f "$CONFIG_PATH" ]; then
    cat "$CONFIG_PATH"
  else
    echo "runtime_config.json: 不存在"
  fi
  echo ""

  # ---- 6. smoke ready + NapCat 配置检查 ----
  echo "=============================="
  echo "[6/8] Smoke & NapCat 状态"
  echo "=============================="
  echo "--- smoke ready check ---"
  if [ -f "$WORKSPACE/.venv/bin/python" ]; then
    "$WORKSPACE/.venv/bin/python" "$WORKSPACE/scripts/check_current_session_smoke_ready.py" 2>&1 || echo "[脚本执行失败]"
  fi
  echo ""
  echo "--- NapCat 配置 ---"
  NAPCAT_CONF="${NAPCAT_ONEBOT_CONFIG:-/root/Napcat/config/onebot11_3940223711.json}"
  if [ -f "$NAPCAT_CONF" ]; then
    echo "存在: yes"
    python3 -c "
import json
with open('$NAPCAT_CONF') as f:
    d = json.load(f)
# 只显示非敏感字段
safe = {k: v for k, v in d.items() if k.lower() not in ['token','secret','password','access_token']}
print(json.dumps(safe, indent=2, ensure_ascii=False))
" 2>/dev/null || echo "[脱敏失败，回退显示文件名]"
  else
    echo "NapCat配置: 不存在 $NAPCAT_CONF"
  fi
  echo ""

  # ---- 7. systemd 状态 ----
  echo "=============================="
  echo "[7/8] systemd 状态"
  echo "=============================="
  systemctl status yangyang-nonebot.service --no-pager -l 2>&1 || echo "[服务不存在]"
  echo ""
  echo "--- journalctl 最近15行 ---"
  journalctl -u yangyang-nonebot.service --no-pager -n 15 2>&1 || echo "[无日志]"
  echo ""

  # ---- 8. 端口监听 + 目录结构 ----
  echo "=============================="
  echo "[8/8] 端口 & 目录"
  echo "=============================="
  echo "--- 相关端口监听 ---"
  ss -tlnp 2>/dev/null | grep -E '8080|3000|4001|6099|21100' || netstat -tlnp 2>/dev/null | grep -E '8080|3000|4001|6099|21100'
  echo ""
  echo "--- 项目目录结构 ---"
  find "$WORKSPACE" -maxdepth 3 -not -path "*.venv/*" -not -path "*__pycache__*" -not -path "*.git/*" | sort
  echo ""

  echo "========================================="
  echo "Bundle 结束 — ${TIMESTAMP}"
  echo "========================================="

} > "$OUTFILE"

# 确认输出
echo "✅ Debug Bundle 已生成:"
echo "   $OUTFILE"
echo "   Size: $(wc -c < "$OUTFILE") bytes / $(wc -l < "$OUTFILE") 行"

# 打印前几行预览
echo ""
echo "=== 前10行预览 ==="
head -10 "$OUTFILE"
