# V18 Gemini Work — model efficiency, admission, failover, qualification

**Branch:** `feat/v18-gemini-admission-failover`; based on V17.
**Status:** do not deploy as production without real-provider acceptance.

## Verified user-reported failure
Gemini 3.5 Flash-Lite answered a direct inference request and a LangChain
tool-call test, but the recursive Deep Agents planning run failed after
84.66 seconds with a nested HTTP 503. V17 retried the entire unfinished
plan and exceeded the Work retry allowance. No artifacts were generated.

## Changed design
- **Gemini Live is independent of Work:** no Work planning calls on the
  speech first-audio path. Keep native Live model separately configurable.
- **One fully model-authored structured DAG first:** the primary model
  chooses registered specialists, dependencies, evidence requirements,
  Medium/High thinking and the final QA dependency in one constrained
  response. The existing Work graph validator enforces all required
  sources, formats, dependencies, authorizations and no fake datasets.
- **Escalation for difficult DAGs:** two invalid compact graphs can invoke
  Deep Agents tool-calling replanning. A 503 instead causes model failover,
  not another expensive recursive planning attempt.
- **Shared Gemini gate:** structured cognitive decisions, narrative
  synthesis, Google Search grounded requests, visual QA and artifact
  repair use SQLite WAL-backed process-shared RPM/estimated-TPM limits,
  active request limits, pacing, cool-down and model-specific circuits.
- **Two Gemini Work models:** primary `gemini-3.8-flash` and backup
  `gemini-3.7-flash`. On HTTP 500/502/503/504, try an authorized alternate
  model once. Do not multiply HTTP 429 across models with shared project
  quotas. Authentication and invalid schemas fail closed.
- **Durable Work recovery remains:** WorkStore persists leases,
  specialist receipts, deferred retry and verified artifact publication.
  The gateway cannot fabricate artifact success.

## Configuration
```bash
RIZZLER_WORK_ORCHESTRATOR=deepagents
RIZZLER_WORK_LLM_BACKEND=gemini
RIZZLER_GEMINI_MODEL=gemini-3.8-flash
RIZZLER_WORK_FALLBACK_MODELS=gemini-3.7-flash,gemini-3.8-flash
RIZZLER_QA_MODEL=gemini-3.7-flash
RIZZLER_ARTIFACT_QA=agentic
RIZZLER_WORK_PROVIDER_RPM=6
RIZZLER_WORK_PROVIDER_TPM=24000
RIZZLER_WORK_PROVIDER_PARALLEL=1
RIZZLER_WORK_PROVIDER_GAP_SECONDS=1.5
RIZZLER_WORK_PROVIDER_WAIT_SECONDS=35
```

Use the `compose.v18.yml` overlay with `compose.production.yml`.
The values are conservative defaults, **not the user's Google project
quota**. If provider limits are lower, lower admission settings.

## Release gates
1. Actual key access to both stable Gemini Work models; direct API and
   structured planning calls. Never assume published model availability
   implies access for a particular project.
2. At least one real multi-format financial dataset job completes with
   independently inspectable XLSX, PPTX, PDF/ZIP receipts.
3. A research job finishes with dated, attributable, externally retrieved
   source records; missing figures remain transparent.
4. All 10 Work scenarios complete or show accurately classified failures,
   with no invented data or false completion.
5. Native Gemini Live passes real handoff, interruption, owner isolation,
   memory recall and observed p50/p95/p99 first-audio tests.
6. Fault-injection coverage for 503, 429, 401, invalid DAG, worker crash,
   cancellation and replay. No duplicate publication.
7. Exact final commit: Python 3.11–3.13 CI, security, config, source
   release inventory and real artifact visual/semantic audits.

**Limits:** shared admission is single-host; multi-host needs distributed
Redis/PostgreSQL state. Pre-call tokens are estimates. Google may return
503 on both models, and an outcome cannot be guaranteed until qualified.
