# Rizzler V12 — Unified model-directed agent runtime

Status: **feature branch, not production-qualified**. V12 introduces a shared
controller and leaves existing V11 specialist execution, persistence and QA
intact. It does not certify superiority to any Claude model.

## Wiring

- Finalized Voice STT and authenticated POST /api/agent/turn use the same
  AgentRuntime implementation and authenticated owner identity.
- Production uses one OIDC identity/session (plus CSRF protection for writes).
  Demo uses the same private Voice key and validated session ID for both APIs;
  no Work bearer token is accepted.
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
- New V12 Work jobs persist a pending graph. On worker claim, Gemini
  proposes a capability graph, the trusted validator checks dependencies,
  output coverage and safe dataflow, and the leased worker atomically commits
  and executes its ready nodes. No keyword routing, predetermined task ordering,
  or silent fixed-plan fallback applies to V12 jobs. Legacy submitted V11 jobs
  retain read-only compatibility with their committed execution plans.
  Voice interruption does not cancel durable Work.

## Operation

Configure GEMINI_API_KEY and secure Work storage/signing key.
Production defaults to the agent runtime and model-created Work graph.
Demo opt-in is RIZZLER_AGENTIC_ENABLED=1; without the configured model,
new agentic Work tasks fail closed rather than executing an invented recipe.
The old V11 planner remains only for migration and explicit rollback.

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
1. Model-generated DAG selection and dependency execution now exists for new
   V12 jobs; arbitrary repeated specialist instances and semantic outcome
   grading beyond current structural/evidence gates remain unqualified.
2. All available MCP/connectors exposed through a hardened capability gateway.
3. Live provider qualification, independent source/claim checking, and
   appropriate fallback for grounding remain unverified.
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
