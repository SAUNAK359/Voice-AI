# V26 Phase 1 — Architectural P0: Unified Evidence, Orchestration and Verification

**Implementation scope:** owner-scoped handoff and revision consistency, unified source-investigation contracts, fail-closed execution and publication, recoverable first-failure diagnostics, and release qualification. This is an implementation record, **not** an assertion of production readiness.

## Existing foundations retained

- WorkStore's fenced owner/job leases, immutable authorized DAG, typed stage contracts, durable checkpoints, and independently verified artifact hashes remain authoritative.
- PCCF v2 preserves the immutable goal digest, graph revision, source references, critical metrics, caveats, and dependency edges. Source URLs never automatically become verified facts.
- The V26 Outcome Director differentiates facts that require more source evidence from files that merely await execution.
- LLMs decide substantive investigations, editorial planning and recovery actions. Deterministic guards decide authorization, identity, output scope, source lineage and validity.

## Unified handoff protocol

`work_phase1_protocol.py` defines the same source request contract for upstream and downstream producers. Every V26 backdelegation has an explicitly approved source-obligation ID, authorized recipient, bounded question and reason, and a boolean blocking state. Output-only quality, visualization, or deliverable requirements cannot be represented as missing source facts. Requests without valid references fail closed instead of automatically acquiring a fabricated or guessed ID.

Each output specialist receives an authoritative, immutable handoff manifest:
- authenticated owner and job scope;
- approved goal digest and unchanged user-authorized output formats;
- exact current PCCF revision;
- required source/evidence IDs, critical numerical metrics and uncertainties;
- specialist identity and a canonical receipt hash.

The manifest is recomputed against the persisted user job and graph. A changed source graph revokes older handoffs, while unchanged source/checkpoints can be reused. Freshness and identity are checked **before execution**, **before artifact promotion**, and **before final QA**. The per-specialist persisted result records the graph revision and exact handoff digest, so reopened agents reject stale cached results even if the legacy report text or ArtifactIR hash did not change.

## Execution and recovery contract

1. The authorized WorkStore DAG and tenant/fence remain immutable.
2. Context convergence produces a source-scoped, revised PCCF graph.
3. Each renderer and the final Quality Agent checks their handoff against the **same** graph and user permission envelope.
4. On planning or rendering failure, a sanitized `failure_origin` event records specialist, stage, attempt, typed error and graph revision **before** any LLM-led retry.
5. The recovery LLM selects replan, rerender, authorized source request or abort; no action grants a new permission or changes source truth.
6. A source request is checked against the same typed source-obligation validator at recovery selection, feedback, context convergence and escalation; stale/output-only/malformed requests are rejected.
7. Source changes invalidate downstream checkpoints. A resumed specialist must verify the latest handoff digest and content-addressed output receipt.
8. Final output QA verifies the exact source-graph revision and actual artifact bytes. Numeric audit rejection and unobserved critical metrics emit bounded, privacy-safe cause events without raw model text or user data.

## Regressions and acceptance

`tests/test_v26_phase1_protocol.py` checks real PCCF migration and graph validation, per-specialist coherent handoffs, changing immutable formats, tenant/job forgery, stale source revisions, canonical tampering, valid source inquiries across three agents, unauthorized recipients, and invalid output-only evidence requests.

`scripts/qualify_v26_live.py` includes the Phase-1 suite in its offline preflight. The existing Python 3.11/3.12/3.13 CI, native artifact and application suites must pass at the **final source SHA**.

## Explicit limitations / release gate

- No offline test can establish that Gemini will always produce correct, high-value content or choose a successful repair.
- The original Kaggle PowerPoint planning rejection was not yet reproduced with its complete planner-specific reason. Future live runs retain the first typed failure before recovery.
- The separate live numerical `ConsistencyViolation` has not yet been attributed to an exact claim/extraction mismatch. Source-bound audit remains strict; it is **not** silenced.
- Real multi-format paid-provider replay, cross-domain trials, concurrency/503 endurance, security/load testing, human reviews and G00–G17 evidence remain mandatory.
- Feature flags default OFF for unqualified production scopes. Complete production readiness is a later evidence-backed decision, never implied by a passing unit test or this document.
