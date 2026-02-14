# MVP Stabilization Plan

## Problem List (4 blocks)

### 1) Intent routing
- Misroutes between chat/run/actions on ambiguous inputs
- No confidence threshold or clear fallback path
- Missing explicit intents for memory/reminders edge cases

### 2) Memory ("запомни") + Reminders ("напомни")
- "запомни" does not reliably persist or recall facts
- No edit/delete flow for stored memories
- "напомни" scheduling is inconsistent and lacks timezone clarity
- Reminders do not surface consistently in UI notifications

### 3) Web browsing + Desktop control
- Browsing tool not stable or not wired for citations
- No robust error handling or retry for web fetch
- Desktop control permissions/handshake unclear or incomplete
- No safe-guarded action confirmations for desktop operations

### 4) Tone/Style
- Tone shifts between system/assistant voices
- Overly verbose or overly curt responses in runs
- Missing style guide for status updates and errors

## MVP Stable Readiness Criteria
- Intent routing passes core smoke set with >=95% correct routing
- "запомни" persists and recalls within the same session and across restarts
- "напомни" schedules, fires, and can be listed/edited/removed
- Web browsing returns answers with citations and graceful failures
- Desktop control requires explicit permission and logs all actions
- No critical crashes in run loop or UI during 30-minute usage

## Order of Work (10–20 items)
1. Define intent taxonomy and update router tests.
2. Add confidence threshold + fallback to clarifying question.
3. Implement memory write pipeline for "запомни".
4. Implement memory read pipeline and retrieval ranking.
5. Add memory edit/delete commands and UI affordances.
6. Implement reminders storage model and scheduler.
7. Add timezone parsing and reminder time normalization.
8. Implement reminder list/edit/cancel flows in UI.
9. Wire web browsing tool with citation formatting.
10. Add web error handling, retries, and timeout UX.
11. Gate desktop control behind explicit permission prompt.
12. Add desktop action registry with confirmations.
13. Add e2e smoke tests for run + memory + reminders.
14. Align tone/style copy for run status and errors.
15. Add basic telemetry/logging for failures and routing stats.
