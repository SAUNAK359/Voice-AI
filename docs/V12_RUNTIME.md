# Rizzler V12 — Unified model-directed agent runtime

Status: **feature branch, not production-qualified**. V12 introduces a shared
controller and leaves existing V11 specialist execution, persistence and QA
intact. It does not certify superiority to any Claude model.

## Wiring

- Finalized Voice STT and authenticated POST /api/agent/turn use the same
  AgentRuntime implementation and authenticated owner identity.
- Production identity is OIDC and CSRF; development sessions require the
  private voice access key and validated X-Session-Id.
- App's Work API and Voice both access the same durable WorkStore; jobs are
  visible by status/plan/agents/events/artifacts across both surfaces.
- Installed capabilities are described to the planning model at runtime.
  The model chooses calls dynamically; no keyword-to-action matching exists
  in the V12-enabled voice path.
- Tools run in bounded rounds, independent reads can be concurrent. Work
  submission persists a job but never claims an artifact is already ready.
- Owner-scoped mutation proposals for Work cancel/revise/retry require a
  separate authenticated user action. Revision/retry creates a new immutable
  job linked to the previous version. Confirmation IDs expire.
- Existing WorkWorker executes specialist DAG nodes and uses the original QA
  and artifact publishing checks. Voice interruption does not cancel Work.

## Operation

Configure GEMINI_API_KEY and secure Work storage/signing key.
Production defaults to the new agent runtime. To opt in on demo, set
RIZZLER_AGENTIC_ENABLED=1. To roll back semantic orchestration temporarily,
set RIZZLER_AGENTIC_ENABLED=0; existing V11 VoiceTools remain available.

The main application provides a text control and the same microphone voice
channel. POST /api/agent/turn expects {"text":"..."}; response includes
answer, tool diagnostics, accepted job or approvals when applicable.
POST /api/agent/approvals/{id}/confirm performs a separately authenticated
mutation. Equivalent Work HTTP endpoints expose revisions, retries, lineage
and confirmation.

### Security and failure behavior

- The model receives no credential and cannot supply an owner identity.
- Tool parameters are schema-checked; unknown capabilities fail closed.
- No arbitrary shell, external email/send, payments, or arbitrary MCP actions
  are exposed by this increment.
- Only explicit confirmation executes destructive/mutating Work operations;
  prepare does not alter the targeted job.
- Real provider errors and offline quota limits must be independently tested.
- Untrusted tool text is task evidence, not authority to change permissions.
- Accepted jobs can continue after the voice WebSocket disconnects.
- The agent loop is bounded and may return partial progress or uncertainty.

## Outstanding qualification and architectural work

**These are not claimed completed:**
1. True dynamic Work specialist dependency graphs and task-specific goal grading:
   the existing fixed V11 Work DAG still executes accepted jobs.
2. All available MCP/connectors exposed through a hardened capability gateway.
3. Robust live provider evaluation, external source/claim checking, and provider
   fallback for grounding; existing grounded-search caveats remain.
4. Model-driven long-horizon self-improvement, safe procedural skill updates.
5. Real device acoustic latency, TTS interruption and mobile browser soak.
6. Live 2-user OIDC, PostgreSQL and multi-host storage tests.
7. PDF/Office artifact semantics and visual inspection quality in real workflows.
8. Red-team prompt injection and production penetration testing.
9. Comparative Claude benchmark with a pinned model/version and equivalent tools.

### Release gates

Before merging require green App CI, offline CI, CodeQL and production config
checks; real Gemini calls; authorized Work create/monitor/download/revise/cancel
across voice/text; kill/restart WorkWorker and replay; expired approval tests;
artifact truth audits; and real-browser end-to-end trials.
