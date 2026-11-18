# V23 Cognitive Foundation — Implementation and Qualification

**Branch:** `feature/v23-cognitive-evidence-foundation`  
**PR:** #47 (draft) against `feature/v23-hace-hierarchical-runtime`  
**Status:** foundations implemented; live Kaggle research, document-level citation accuracy, multiagent performance and strict visual qualification remain unverified.

## What is implemented in this branch

| Component | Source | Behavior |
| --- | --- | --- |
| Full phase-by-phase design | `docs/V23_COGNITIVE_EXECUTION_PLAN.md` | Architecture, contracts, fault cases, acceptance gates |
| Job cognitive ledger | `work_store.py`, `work_api.py` | Owner-scoped event stream with immutable SHA-256 content receipts, monotonic cursors, lease-fenced publication |
| Agent awareness | `work_specialists.py` | Checkpoint success atomically publishes findings; downstream composition sees shared committed summaries |
| Inverse-pyramid planner | `cognitive_director.py`, `hace_runtime.py` | Model authors task-specific briefs; validating approvals and hierarchical structure prevents permission escalation |
| Source ingestion | `source_normalizer.py` | HTML, Markdown, PDF text and tables, CSV, XLSX, JSON; source hashes, section/page/sheet provenance, warnings |
| Safe evidence gateway | `source_gateway.py` | HTTPS only, public-IP DNS resolution, checked redirects, bounded streamed bodies, no credentials/proxies |
| Provider research | `work_worker.py` | Optional actual page retrieval, source extraction, domain-specific synthesis, explicit retrieval errors |
| Deep content authoring | `content_engine.py`, `work_worker.py` | Model-chosen section plan, bounded parallel development with verified dataset context |
| Rendering cleanup | `work_design.py` | Eliminate raw Markdown control tokens from displayed outputs, increase cover title fit |

**Important:** The existing WorkStore DAG remains executable authority. The director's hierarchy is advisory, not a fully dynamic subagent execution graph. A truly extensible agent registry, claim-level verification, evaluation-trained memory, dependency-aware artifact repair, and autonomous format-specific storyboards are not yet implemented.

## Opt-in experimentation

These switches are disabled by default until live qualification. To try cognitive research/content development on Kaggle, set them **before starting the worker**:

```bash
export RIZZLER_COGNITIVE_PLANNER=1
export RIZZLER_COGNITIVE_CONTENT=1
export RIZZLER_EVIDENCE_FETCH=1
```

Use an existing paid Gemini API key via `GEMINI_API_KEY`. Keep API credentials in Kaggle Secrets or an external secret store. Do not print tokens, commit notebook output or grant agents raw shell access.

- `RIZZLER_COGNITIVE_PLANNER=1`: one optional model call validates task-specific expert briefs against the approved graph. Failure records a gap and retains existing execution.
- `RIZZLER_COGNITIVE_CONTENT=1`: section plan plus up to three concurrent draft requests per running Work job. It raises on inadequate content; it does not silently issue a short generic report.
- `RIZZLER_EVIDENCE_FETCH=1`: fetch up to eight provider-grounded HTTPS URLs with three simultaneous requests, source-byte limits and error categories; optional secondary synthesis uses extracted text and tables.
- `RIZZLER_ARTIFACT_QA=strict`: renders and inspects output pages where PyMuPDF/LibreOffice are installed; otherwise structural QA remains the default and does NOT certify visual quality.

Use the existing V11 native Kaggle runtime as the launcher, replacing its `REF` with this feature branch; do **not** enable new features in production until passing the full matrix.

## Offline checks

```bash
python scripts/verify_release.py
python -m unittest tests.test_v23_hace_runtime tests.test_v23_cognitive_foundation tests.test_v23_content_engine tests.test_v23_source_gateway -v
python -m unittest discover -s tests -v
python scripts/scan_secrets.py
```

Run with `pip install -e '.[work,test]'`. This installs optional acquisition, document and model client requirements. CPU CI cannot certify provider availability, VPN/browser microphone permissions, GPU ASR, true web factual accuracy or aesthetic quality.

## Acceptance work still required before merge/deployment

1. Live model-planner test: valid JSON, prompt-injection attempts, 503/429 timeout handling, specialized depth and unchanged tool permissions.
2. Evidence tests: genuine official sources with table/period reconciliation, blocked JavaScript shells, redirect host changes, PDF scans and provenance comparison.
3. Deep content tests: domain-expert blind review, distinct meaningful findings, coverage of all user requirements, citations, contradiction detection, no redundant sections.
4. Cross-agent tests: parallel specialists with job restart, no duplicate cognitive events, owner isolation, ledger tampering refusal and voice status updates.
5. Artifact tests: PPTX/DOCX/XLSX/PDF visual output, formula consistency, source-support mapping, page occupancy and targeted repair.
6. Reliability/efficiency: sustained workload concurrency, provider outages and exponential retry, P50/P95 latencies, call/token/price budgets, workflow cancellation and idempotent recovery.

**Never guarantee zero failures:** outages, corrupt external documents, unsupported formats, blocked sites, bad evidence, sandbox limits and provider quotas are real constraints. Correct behavior is bounded recovery or an honest incomplete result.
