# Framework Sync Release Note — 2026-06-19

## Summary
This round packages the useful framework work into a stable git checkpoint for future handoff, rollback, and continued development.

## Included useful work

### 1. Owner private session-state compression V1
- compact rolling summary backfill for long private-chat history
- prompt assembly prefers `rolling_summary + limited recent history`
- session-state control flow supports suspend / resume markers and diff hints

### 2. Factory auto-report line cleanup
- removed deprecated `factory_completion_notifier` registration from active scheduler boot path
- stopped repeated minute-level skip/dedup noise from the old notifier path
- retained factory assets as manual scouting / draft capability only

### 3. SSE send_stream guardrails
- added disconnect sensing during stream loop
- tightened finished-state / enqueue / cancellation handling
- reduced half-dead proxy teardown risk on SSE path

### 4. Fallback behavior verification
- ordinary fallback preserves useful continuity
- safety fallback remains intentionally isolated from sensitive original content

### 5. Operator/tooling/docs enrichment
- operator docs and incident records updated
- host-side common inspection tools verified/available in recent round

## Validation snapshot
- owner private prompt/session-state targeted regression: 50 passed
- factory notifier + session-state + prompt-context regression bundle: 54 passed
- latest mainline sync verification snapshot: 68 passed

## Git anchors
- main feature sync commit: `e102600`
- milestone tag: `framework-sync-20260619`

## Notes
- This is a framework usefulness sync, not a new feature blast.
- The practical value is in controllability, observability, and continuity — not in fake busy multi-agent theater.
