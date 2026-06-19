PASS
Task: Framework useful-parts sync / release-note closeout

Changed scope summary:
- Owner private session-state compression V1 landed and verified.
- Factory auto-report notifier registration removed from active scheduler path.
- send_stream SSE disconnect/teardown guardrails landed.
- Fallback continuity / safety-fallback behavior verified.
- Tooling and operator docs enriched for current maintenance line.

Core change bullets:
1. Owner private context/session-state
   - long-history private session now supports compact rolling summary backfill
   - prompt assembly prefers rolling summary + limited recent turns
   - suspended/resume control flow and diff hints wired into state transitions
2. Factory line cleanup
   - deprecated automatic factory report line removed from scheduler boot path
   - repeated dedup skip noise no longer wakes every minute from active registration
   - factory assets retained only as manual/探路/草稿能力
3. SSE stability
   - disconnect sensing and teardown guardrails added on send_stream path
   - cancellation / finished-state enqueue behavior tightened
4. Verification
   - owner private prompt/session-state targeted pytest: 50 passed
   - factory notifier / session-state / prompt-context regression bundle: 54 passed
   - prior send_stream guardrail targeted pytest: PASS
   - latest mainline verification on sync push round: 68 passed

Release note:
- This sync packages the useful framework work from the recent rounds into a traceable git state.
- High-value outcomes are not cosmetic multi-agent theatrics; they are practical control improvements around session memory, streaming stability, scheduler noise reduction, and operator tooling.
- The black-factory automatic push line is intentionally de-emphasized for now; future factory usage stays manual/self-built until a real controllable spec exists.

Tag intent:
- recommended milestone tag for this sync round: framework-sync-20260619
- purpose: fast rollback / lookup anchor for the current stable framework checkpoint

Operator close:
- Git mainline is now the source of truth for this round.
- Follow-up should continue from this stable checkpoint instead of reopening already-closed notifier/autopush logic.
