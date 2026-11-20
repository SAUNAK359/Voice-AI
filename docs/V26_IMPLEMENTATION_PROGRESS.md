# Rizzler V26 — Implementation Tracker and Release Evidence Contract

**Specification of record:** user-authored final upgrade blueprint,
RIZZLER_V26_FINAL_UNIVERSAL_COGNITIVE_WORK_UPGRADE_SPEC.md (2026-11-20).

**Status:** IN PROGRESS. Not certified as production or industry-competitive.
The retained V25 branch is the migration baseline; new capabilities are
opt-in until the real provider, document, database and adversarial gates pass.

## Implemented in first V26 integration tranche

### Phase A — Correct source readiness versus unfinished deliverables
- work_outcome_phases.py: typed six-phase outcome lifecycle, source/output
  scope, evidence request binding and phase projections.
- work_context_intelligence.py / work_feedback.py: the source preflight
  distinguishes absent future PPTX/DOCX/PDF/XLSX/ZIP files from genuine
  source gaps. Model requests bound to output-only obligations are removed
  while source-bound investigation requests remain in force.
- Original user goals and approved specialist permissions are immutable.
- Regression tests include the original V25 false context blocker.

### Phase B — Proof-Carrying Context Fabric (schema version 2)
- work_context_fabric.py: typed node graph covering goals, requirements,
  sources, evidence spans, metrics, insights, recommendations, decisions,
  uncertainties and artifact components, with provenance status, content
  digest, dependencies and graph validation.
- Strict owner/job/specialist-scoped exact-node retrieval and role context
  views with declared omissions and hard-fact preservation.
- Transitive dependency invalidation and no fabricated promotion of V25
  report text to independently verified facts.
- WorkStore: fenced, per-job immutable-authorization graph persistence,
  checksum verification, owner isolation and source-revision-aware replay.
  Database tables use DDL compatible with the existing PostgreSQL adapter.
- work_specialists.py: after source convergence, reconstruct or rehydrate
  the authorized context graph and share role-aware slices.

### Phase C initial — Source-bound numerical reasoning
- work_reasoning_audit.py: Gemini selects whether a particular uploaded
  dataset needs a two-measure analysis and the exact source columns.
- The verifier computes group differences and total arithmetic from input
  bytes using Decimal, without trusting model-generated numeric results.
- Unsupported causal identification is rejected; uniformity, direction,
  totals and confounder overlap are explicit machine-checkable predicates.
- The independently executed receipt is committed to role-scoped PCCF,
  including units, source digest and essential methodological limitations.
- tests/test_v26_reasoning_audit.py exercises the exact four-row misleading
  deficit, region/time confounding and nonfinite/bogus input fixtures.

### Phase C / D initial — Editorial relevance and PowerPoint source coverage
- work_editorial_director.py: model-selected source sections with a complete
  inclusion/exclusion ledger, permitted citations and separate critic verdict.
- work_artifact_strategy.py: source-scoped editorial strategy reuses approved
  V25 PowerPoint generation and preserves original section ID lineage.
- work_studio.py: editorial scope validation permits a shorter, purposeful
  deck without requiring every technical log to become a slide. Legacy
  coverage remains unchanged unless the feature is explicitly enabled.
- Existing per-format strict validation and bounded repair remain intact.

### Rollout controls
V26 flags default OFF. The foundational context/phase/graph flags must
be enabled together; editorial behavior must be enabled deliberately.
- RIZZLER_V26_CONTEXT_FABRIC
- RIZZLER_V26_OUTCOME_PHASES
- RIZZLER_V26_INSIGHT_GRAPH
- RIZZLER_V26_EDITORIAL_DIRECTOR

### New tests
- tests/test_v26_outcome_phases.py
- tests/test_v26_context_fabric.py
- tests/test_v26_editorial_strategy.py

Offline tests validate schemas, tenant isolation, source-authorization,
technical-log exclusion, source-revision replay and selected slide coverage.

## NOT YET IMPLEMENTED OR QUALIFIED

The following are **explicitly open**; do not call the upgrade finished:
- Provenance span acquisition/storage hardened for every retrieval class
- Domain method registry, independent statistical/scientific reasoning audits
- Claim/metric-level cross-document consistency and numerical language guard
- Native PowerPoint semantic chart strategy and actual visual image critic
- Advanced Excel scenario models, charts, pivots and editorial dashboard strategy
- Extended Word/PDF publication-quality editorial and visual QA
- Code/UI specialists and interactive dashboard execution integration
- Provider outage/429/503 endurance, load/performance/cost measurements
- 200 MB secure streamed ingestion and all high-context security conditions
- Full-schema owner-memory retention/expiry and correction lifecycle
- Frozen multi-domain evaluations (120+ tasks), blind human grading
- Staging, rollback, operations, SLO and final signoff

## Required release decision

The V26 specification defines 18 gates G00–G17. Until independently
demonstrated, these gates are NOT_RUN, not PASS. The true release state is
NOT_READY, even if all current GitHub CI checks succeed.

Do not merge PR56 or advertise professional/production certification based
solely on syntax, a PDF opening, passing isolated unit tests, or a provider
preflight. Use real source-bound tasks, adversarial suites, strict rendered
artifact review and owner-authorized releases.
