# I_LINE MVP Stable Host Smoke Runbook

Status: **RUNBOOK_ONLY / NO HOST ACTION EXECUTED BY BACKGROUND TASK**  
Date: 2026-06-07  
Bundle: `dist/i_line_mvp_stable_20260607.zip`

This runbook is for a human/operator on the host. The bundle generation task must not access the production host path, deploy, restart services, call network providers, or modify runtime config / `.env` / long-term memory.

## 0. Stop-the-line rules

Stop immediately if any condition is true:

- Package SHA differs from manifest.
- Any unexpected P2 implementation, real provider adapter, IsaacExecutor, shell execution, service-control code, or network provider config appears in the apply set.
- `runtime_config`, `.env`, or long-term memory SHA changes unexpectedly.
- `pytest tests/test_i_line_*.py` fails.
- Group chat receives an I_LINE/Isaac reply.
- Private owner smoke emits a real dispatch/executor/provider/network signal.

## 1. Operator variables

Use host-local values; placeholders below are not executed by this task.

```bash
HOST_PROJECT="<HOST_PROJECT_ROOT>"
BUNDLE="<PATH_TO>/i_line_mvp_stable_20260607.zip"
BACKUP_DIR="<HOST_BACKUP_DIR>/i_line_mvp_stable_$(date +%Y%m%d_%H%M%S)"
SERVICE_NAME="<NONEBOT_SERVICE_NAME>"
```

## 2. Apply-before checks

```bash
cd "$HOST_PROJECT"
python3 --version
python3 -m pytest --version
sha256sum "$BUNDLE"
unzip -l "$BUNDLE"
```

Verify manually:

- Bundle only contains the stable file list from `I_LINE_MVP_STABLE_BUNDLE_20260607.md`.
- No P2 implementation file is present.
- No runtime config / `.env` / long-term memory file is present in the bundle.
- Current service is healthy enough to restart after apply.
- Current OneBot adapter is connected or has a known baseline state.

## 3. Pre-apply SHA snapshot

Record hashes before touching code:

```bash
mkdir -p "$BACKUP_DIR"
sha256sum src/plugins/yangyang/data/runtime_config.json > "$BACKUP_DIR/runtime_config.before.sha256" || true
sha256sum .env > "$BACKUP_DIR/env.before.sha256" || true
find src/plugins/yangyang/data -path '*long_term*' -type f -print0 | sort -z | xargs -0 sha256sum > "$BACKUP_DIR/long_term.before.sha256" || true
```

## 4. Backup current apply targets

```bash
mkdir -p "$BACKUP_DIR/files"
cp -a src/plugins/yangyang/__init__.py "$BACKUP_DIR/files/yangyang.__init__.py" || true
cp -a src/plugins/yangyang/core/isaac_agent_bus_p0.py "$BACKUP_DIR/files/isaac_agent_bus_p0.py" || true
cp -a src/plugins/yangyang/core/isaac_intent_p1.py "$BACKUP_DIR/files/isaac_intent_p1.py" || true
cp -a src/plugins/yangyang/core/isaac_intent_provider_bridge_p15.py "$BACKUP_DIR/files/isaac_intent_provider_bridge_p15.py" || true
cp -a tools/agent_bus/agent_bus_a1_schema.py "$BACKUP_DIR/files/agent_bus_a1_schema.py" || true
cp -a tests "$BACKUP_DIR/files/tests_before_i_line" || true
```

## 5. Apply stable bundle

Recommended safe overlay:

```bash
mkdir -p "$BACKUP_DIR/unpacked"
unzip -q "$BUNDLE" -d "$BACKUP_DIR/unpacked"
rsync -av "$BACKUP_DIR/unpacked/" "$HOST_PROJECT/"
```

Then verify the overlay did not add forbidden runtime material:

```bash
find src/plugins/yangyang/data -maxdepth 4 -type f | sort
unzip -l "$BUNDLE" | grep -E 'runtime_config|\.env|long_term|memories\.jsonl' && echo 'STOP: forbidden data file in bundle'
```

## 6. py_compile

```bash
python3 -m py_compile   src/plugins/yangyang/__init__.py   src/plugins/yangyang/core/isaac_agent_bus_p0.py   src/plugins/yangyang/core/isaac_intent_p1.py   src/plugins/yangyang/core/isaac_intent_provider_bridge_p15.py   tools/agent_bus/agent_bus_a1_schema.py
```

## 7. pytest regression

```bash
python3 -m pytest -q tests/test_i_line_*.py
```

Expected: all I_LINE tests pass.

## 8. Post-apply SHA snapshot

```bash
sha256sum src/plugins/yangyang/data/runtime_config.json > "$BACKUP_DIR/runtime_config.after.sha256" || true
sha256sum .env > "$BACKUP_DIR/env.after.sha256" || true
find src/plugins/yangyang/data -path '*long_term*' -type f -print0 | sort -z | xargs -0 sha256sum > "$BACKUP_DIR/long_term.after.sha256" || true
diff -u "$BACKUP_DIR/runtime_config.before.sha256" "$BACKUP_DIR/runtime_config.after.sha256" || true
diff -u "$BACKUP_DIR/env.before.sha256" "$BACKUP_DIR/env.after.sha256" || true
diff -u "$BACKUP_DIR/long_term.before.sha256" "$BACKUP_DIR/long_term.after.sha256" || true
```

Expected: no unexpected diff. If any protected data SHA changes, stop and rollback.

## 9. Service restart and connection check

Operator-only host action:

```bash
systemctl restart "$SERVICE_NAME"
systemctl status "$SERVICE_NAME" --no-pager
journalctl -u "$SERVICE_NAME" -n 200 --no-pager
```

Expected log checks:

- NoneBot service starts cleanly.
- OneBot adapter/reverse WebSocket reports connected.
- No import error for `isaac_agent_bus_p0`, `isaac_intent_p1`, or `isaac_intent_provider_bridge_p15`.
- No P2/real-provider/IsaacExecutor startup line appears.

## 10. Private owner smoke

From owner private chat only:

| Input | Expected |
| --- | --- |
| `I叔 help` | One reply. Contains `I叔 P0 闭环已跑通`, command list, owner-private/high-risk boundary. |
| `i叔 health` | One reply. Contains `TaskRequest -> Isaac worker -> TaskResult`, `executor_enabled=false`, `host_action_executed=false`, `workspace_only=true`, `read_only=true`. |
| `艾萨克 看一下工作区情况` | One reply. Contains `I叔 P1 preview`, `would_dispatch_dry_run`, `intent=workspace_report`, `task_request_dispatched=false`, `provider_network_used=false`. |
| `I叔 你看这个是不是有问题？` | One reply. Contains `clarification_required`; no TaskRequest/worker result. |
| `I叔 帮我 systemctl restart 服务` | One reply. Contains `high_risk_blocked`; no dispatch/executor/provider. |
| `isaac health` | No I_LINE/Isaac reply. |

## 11. Group negative smoke

From group chat, including owner account:

| Input | Expected |
| --- | --- |
| `I叔 health` | No group reply and no I_LINE/Isaac exposure. |
| `艾萨克 看一下系统状态` | No group reply and no provider preview. |

Check logs only for safe internal traces; public group output must stay empty.

## 12. Rollback

If any stop condition occurs:

```bash
cd "$HOST_PROJECT"
cp -a "$BACKUP_DIR/files/yangyang.__init__.py" src/plugins/yangyang/__init__.py || true
cp -a "$BACKUP_DIR/files/isaac_agent_bus_p0.py" src/plugins/yangyang/core/isaac_agent_bus_p0.py || true
cp -a "$BACKUP_DIR/files/isaac_intent_p1.py" src/plugins/yangyang/core/isaac_intent_p1.py || true
cp -a "$BACKUP_DIR/files/isaac_intent_provider_bridge_p15.py" src/plugins/yangyang/core/isaac_intent_provider_bridge_p15.py || true
cp -a "$BACKUP_DIR/files/agent_bus_a1_schema.py" tools/agent_bus/agent_bus_a1_schema.py || true
python3 -m py_compile src/plugins/yangyang/__init__.py src/plugins/yangyang/core/isaac_agent_bus_p0.py src/plugins/yangyang/core/isaac_intent_p1.py src/plugins/yangyang/core/isaac_intent_provider_bridge_p15.py tools/agent_bus/agent_bus_a1_schema.py
python3 -m pytest -q tests/test_i_line_*.py
systemctl restart "$SERVICE_NAME"
systemctl status "$SERVICE_NAME" --no-pager
```

After rollback, repeat the protected SHA checks and group negative smoke.
