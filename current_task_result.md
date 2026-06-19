PASS
Task: send_stream SSE disconnect/teardown guardrails patch

Changed files:
- src/plugins/yangyang/__init__.py
  - /yy/api/chat/send_stream now checks request.is_disconnected() in the stream loop.
  - stream delta callback stops enqueue after finished is set.
  - model-call success/error enqueue guarded by finished state.
  - asyncio.CancelledError handled explicitly for stream task cancellation.
  - cleanup now sets finished, cancels task, and no longer yields proxy_closed inside finally.
  - proxy_closed only emitted on normal non-disconnected teardown.
- tests/test_send_stream_sse_guardrails.py
  - regression guardrails for disconnect check / CancelledError branch / proxy_closed placement.
- PATCH_NOTES_send_stream_sse_guardrails.md
  - patch note and operator summary.

Evidence/diagnosis retained:
- Prior fault signature matched local QQ/WebView/8787 -> 8080 SSE chain entering half-dead HTTP state.
- Old implementation lacked disconnect sensing and yielded proxy_closed from finally cleanup path.

Tests:
- python3 -m py_compile src/plugins/yangyang/__init__.py tests/test_send_stream_sse_guardrails.py: PASS
- ./.venv/bin/python -m pytest -q tests/test_send_stream_sse_guardrails.py: PASS

Constraints:
- Did not restart service.
- Did not run live HTTP smoke against 8080 in this write round.
- Patch reduces hang risk but live verification still needs process reload and runtime retest.


---
2026-06-18 22:24 CST
Follow-up archive:
- Fallback inheritance verification closed:
  - ordinary fallback keeps message content continuity, SessionAnchor retained, fallback metadata/hash/len verified.
  - safety fallback intentionally switches to safe_messages and does not retain original sensitive content or original SessionAnchor.
  - targeted pytest status: tests/test_provider.py -> 14 passed.
- Toolchain improvement on host:
  - installed ripgrep, fd-find, bat, tree, ncdu via apt.
  - added compatibility symlinks: /usr/local/bin/fd -> fdfind, /usr/local/bin/bat -> batcat.
  - command availability verified: rg, fd, bat, tree, ncdu, jq, htop, git, curl, python3.
- Intent:
  - leave written trace before returning to rolling summary / memory mainline.


---
2026-06-18 22:36 CST
Operator note archived:
- Owner explicit restart rule for next live reload: use `sudo systemctl restart yangyang-nonebot`.
- Reason retained: prior restart attempts did not yield immediate NapCat reconnection; restart procedure must follow the systemd service entrypoint exactly for next live verification.
- Action constraint:
  - Do not treat generic reload/restart as equivalent during next smoke.
  - After next real restart, verify service recovery and observe whether NapCat reconnect is immediate or delayed before closing restart-smoke conclusion.
- Next checkpoint intent:
  - restart-smoke should be executed on the real service path above, then record reconnection behavior as evidence.

---
2026-06-19 00:24 CST
Follow-up note:
- Added I叔 black-factory skill docs without service restart.
- Skill directory updated with:
  - data/skills/black-factory-orchestrator-i-shu/SKILL.md
  - data/skills/black-factory-orchestrator-i-shu/reference.md
  - data/skills/black-factory-orchestrator-i-shu/README.md
- Intent:
  - Solidify black-factory dispatch / preflight / corpse-check / report-close workflow into reusable skill guidance.
  - Add short trigger phrases to improve future natural hit rate.
- Runtime note:
  - This is a doc/rule style skill update; no restart performed in this write round.
  - Effective state should be validated by next matching task execution.

---
2026-06-19 00:34 CST
Black-factory auto-report kickoff note:
- Reopened active workline to I叔 NoneBot black-factory auto-report hardening.
- Immediate diagnosis already confirmed three hard blockers in current implementation:
  1. runtime config gates are all OFF by default for current-session owner-action delivery.
  2. production integration call uses explicit_enable=False in main flow, so real current-session send is intentionally never armed.
  3. existing black-factory skill is documentation/process guidance only; it does not yet bind a production auto-report execution hook.
- Meaning:
  - previous “开工” was skill/doc groundwork, not the final production auto-report weld.
  - next step is code patching on NoneBot line, not more doc talk.
- Constraint:
  - no service restart performed in this kickoff note.

## 2026-06-19 NapCat 私聊链路事故补充结论

- 现象：私聊消息可恢复，但重启后日志仍周期性出现 403 / duplicate bot connection。
- 误判点：最初修改到的并非当前 live 进程实际加载的 NapCat 配置，导致重启后问题持续。
- 最终病灶：当前生效配置中的 `network.websocketClients` 仍保留反向 WebSocket 项，NapCat 持续向 `ws://127.0.0.1:8080/onebot/v11/ws` 发起连接，触发重复连接与 403 尾巴。
- 处置：定位真实生效配置，清空 `network.websocketClients`，重启 NapCat 后复验。
- 结果：`测试4`、`测试厕所` 收发正常；403 / duplicate 未再复现。
- 结论：本次事故分两段收口——前段是 `.env`/适配器字段修正恢复主链，后段是 NapCat live 配置清理完成尾巴收口。

2026-06-19 auto-report shutdown note:
- 漂♂总已明确收口：黑奴工厂自动汇报不再继续推进，避免无意义提示骚扰。
- 已关闭运行时开关 `owner_action_auto_reply_current_production_enabled=false`，停止当前会话生产自动回传。
- 已同步把默认值改为关闭，避免后续重启/刷新配置时自动复活。
- 保留工厂用途：仅作为探路、侦查、草稿/文档产出，不再承担自动回传主链职责。


---
2026-06-19 19:25 CST
Owner private session-state compression V1 close note:
- Closed active workline for owner private chat session-state compression V1.
- Core delivery landed in `src/plugins/yangyang/__init__.py`.
- Long-history owner private chat now backfills a compact rolling summary into session state when threshold is reached and no summary exists yet.
- Prompt assembly now prefers `rolling_summary + limited recent history`, reducing dependence on raw long transcript.
- Session-state control flow now supports suspended loop marking, resume by `继续/捡回来`, and diff summary hints including `reason / suspended / resumed`.
- This round intentionally stops at V1 delivery line: rule-based compact summary backfill and stable state-control wiring first; no extra standalone LLM summarization call added in this close round.
- Verification rerun:
  - `./.venv/bin/python -m pytest -q tests/test_owner_private_prompt_context.py tests/test_owner_private_session_state_control_flow.py`
  - Result: 50 passed
- Close decision:
  - deliverable accepted for current phase
  - no infinite optimization in this round


---
2026-06-19 19:28 CST
Factory auto-report notifier removal close note:
- Owner decision confirmed: black-factory automatic report line is deprecated for now; future factory usage stays manual/self-built, not auto-push.
- Root cause of repeated log noise was scheduler-level unconditional registration of `factory_completion_notifier`, which kept waking every minute and logging dedup skips even after production auto-reply was disabled.
- Code removal landed in `src/plugins/yangyang/tasks/__init__.py`:
  - removed notifier import from active scheduler boot path
  - removed `factory_completion_notifier` interval job registration
- Regression update landed in `tests/test_factory_completion_notifier.py`:
  - scheduler assertion now verifies `factory_completion_notifier` is absent
  - targeted notifier behavior tests remain available as dormant asset coverage
- Verification rerun:
  - `pytest -q tests/test_factory_completion_notifier.py tests/test_owner_private_session_state_control_flow.py tests/test_owner_private_prompt_context.py`
  - Result: 54 passed
- Close decision:
  - automatic factory notifier stays removed from live scheduler path
  - no more minute-level skip spam from this job source after process reload
