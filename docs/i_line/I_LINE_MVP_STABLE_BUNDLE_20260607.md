# I_LINE MVP Stable Bundle（Read-only Health Bundle）

Status: **STABLE_FOR_HOST_SMOKE**  
Date: 2026-06-07  
Scope: owner-private read-only MVP only. P2 real provider implementation remains **NO-GO**.

## 1. MVP capability scope

This stable bundle contains only the already-covered I_LINE read-only minimum path:

| Area | Stable behavior |
| --- | --- |
| Trigger | Only owner private messages containing `I叔`, `i叔`, or `艾萨克` trigger I_LINE handling. Trigger position is intentionally unrestricted. |
| English negative | `isaac` / `/isaac` do **not** trigger. |
| Channel boundary | Group messages do **not** trigger or expose I_LINE/Isaac content. Non-owner private messages do not expose I_LINE internals. |
| Explicit P0 commands | `help`, `health`, `workspace report`, `dry_run plan` run the in-memory read-only P0 closure: sanitized TaskRequest -> built-in read-only Isaac worker -> sanitized TaskResult. |
| Natural language delegation | Low-risk owner-private aliases for health/workspace/dry-run/help return P1 preview `would_dispatch_dry_run`; they do **not** dispatch a real TaskRequest. |
| Ambiguous requests | Return clarification and no dispatch. |
| High-risk requests | Block before provider/bus/worker path. Markers include restart/deploy/shell/systemctl/service/runtime_config/.env/long_term/memory/secret-style requests. |
| Provider bridge | P1.5 bridge is default-off. Fixture mode is local-test-only and does not authorize provider/network usage. |

## 2. Stable included implementation

The host smoke overlay should only need these project files from this bundle:

- `src/plugins/yangyang/__init__.py` — owner-private plugin integration gate.
- `src/plugins/yangyang/core/isaac_agent_bus_p0.py` — P0/P1 handler, in-memory sanitized Agent Bus closure, high-risk and redaction guards.
- `src/plugins/yangyang/core/isaac_intent_p1.py` — deterministic local intent dry-run parser and provider-contract validator.
- `src/plugins/yangyang/core/isaac_intent_provider_bridge_p15.py` — default-off local fixture provider bridge only.
- `tools/agent_bus/agent_bus_a1_schema.py` — passive schema validation helper used by P0.
- `tests/test_i_line_*.py` and `tests/fixtures/i_line_p1_4_natural_delegation_matrix.jsonl` — regression suite.
- `docs/i_line/I_LINE_MVP_STABLE_HOST_SMOKE_RUNBOOK_20260607.md` — host smoke steps.

## 3. Explicit non-goals / excluded from stable bundle

- No P2 real provider implementation.
- No network LLM/provider calls.
- No IsaacExecutor integration.
- No real Agent Bus runtime dispatch.
- No shell/subprocess/os.system/systemctl calls from code.
- No writes to runtime config, `.env`, or long-term memory data.
- No production host deployment, service restart, or host path access by this task.

P2 design/spec documents may remain in the repository for later review, but they are not part of this stable host smoke bundle and must not be applied as implementation.

## 4. Expected smoke behavior

Owner private positives:

1. `I叔 help` -> P0 PASS, shows commands and boundary.
2. `i叔 health` -> P0 PASS, read-only closure, `executor_enabled=false`, `host_action_executed=false`.
3. `艾萨克 看一下工作区情况` -> P1 preview `would_dispatch_dry_run`, no TaskRequest dispatch.
4. `I叔 你看这个是不是有问题？` -> clarification, no dispatch.
5. `I叔 帮我 systemctl restart 服务` -> high-risk blocked before provider/bus.

Negatives:

1. `isaac health` or `/isaac health` -> not handled.
2. Group `I叔 health` -> no public reply / no I_LINE exposure.
3. Non-owner private `I叔 health` -> no I_LINE internals exposure.

## 5. Host smoke readiness verdict

This bundle is ready for **manual host smoke only** if and only if:

- package SHA matches the manifest;
- py_compile passes on the listed files;
- `pytest tests/test_i_line_*.py` passes;
- runtime config / `.env` / long-term memory SHA snapshots are unchanged before and after apply;
- OneBot connection is already healthy after service restart;
- private and group smoke expectations match this document.
