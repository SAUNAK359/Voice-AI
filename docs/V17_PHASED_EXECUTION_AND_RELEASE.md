# Rizzler V17 — Implementation Phases and Release Qualification

**Branch:** `feat/v17-production-execution-hardening` (draft PR #38)  
**Base:** V16 PR #37. **Do not merge or deploy to production without all release evidence.**

## Architecture boundaries

- **Gemini Live:** interruptible, conversational, medium-interaction model.
  Accepts authenticated Work requests but does not perform long-form work.
- **Deep Agents:** Work planning/subagent deliberation using a qualified local
  reasoning model or an explicitly configured Gemini model. The model chooses
  specialist tools, dependencies, Medium/High thinking and repair proposals.
- **LangGraph:** executes the *model-authored* registered capability DAG in
  dependency waves. No user-keyword routing. The durable job/lease/artifact
  authority remains **WorkStore**; a crashed worker reconstructs the graph
  from its immutable stored plan and skips verified specialist checkpoints.
- **WorkStore PostgreSQL/SQLite:** typed owner authorization, fenced stages,
  idempotent handoff, retry visibility, artifact integrity and publication.
  An additional independent job queue is explicitly prohibited.
- **Keyless research:** private SearXNG, pinned public HTTPS retrieval and
  local reasoning, with original excerpts to support source-linked tables.
- **Documents:** existing Office/PDF native renderers plus mandatory
  agentic/visual QA in the V17 deployment overlay.

## Executed phase changes (source implementation, not live qualification)

| Phase | Changed implementation | Qualification evidence |
|---|---|---|
| P0 | Base V16 audit, separate PR #38 and release manifest | Final CI required |
| P1 | `work_graph_exec.py` drives dependency waves via LangGraph; WorkStore retains fenced receipts | Offline graph-wave and failure tests |
| P2 | `live_native.py` keeps original request separate from model objective, turn-scoped idempotency, explicit external scope | Live schema and job ledger tests; actual voice test pending |
| P3 | `memory_recall` exposes existing opt-in encrypted owner memory to Live | Offline owner/query contracts; live memory qualification pending |
| P4 | `work_structured_research.py` extracts source-linked data rows and refuses invented numeric values | Offline numeric/URL tests; live data verification pending |
| P5 | SGLang 429/5xx classification, bounded retry persistence; incomplete research publication blocked | Offline provider/ledger tests; injected GPU faults pending |
| P6 | Agentic/visual QA deployment mode, research-table repair preservation and extended acceptance runner | Office synthetic tests; external artifact inspection pending |

## Mandatory production gates (all must be evidenced)

1. Exact final Git SHA: Python 3.11/3.12/3.13, JS, full CodeQL,
   release-manifest verification and Compose validation succeed.
2. Deep Agents tool-calling model executes a complete LangGraph DAG on
   a real locally hosted SGLang instance; each stage has owner-fenced receipts.
3. A real Gemini Live request creates exactly one Work job; the original
   voice transcript/typed request and interpreted objective remain separate.
4. Shared owner memory works across Live and Work, updates and deletions do
   not reveal other users; verify behavior during interrupted voice sessions.
5. Live keyless SearXNG finds usable public sources; DNS rebind/redirect
   and prompt-injection tests pass; failures are transparent.
6. Factual values in generated tables are source-linked with exact dated
   excerpts and independently reconciled. Public search does not guarantee
   accurate/complete real-time stock-market data.
7. Native PPTX/DOCX/PDF/XLSX/ZIP outputs must open, render, preserve tables
   and pass content, formula, source, visual and editorial review.
8. Inject 429, 502, 503, lost GPU, rejected graph, malformed JSON, worker
   kill, cancellation and replay. Completed stages remain recoverable and
   there are zero duplicate final publication records.
9. Verify PostgreSQL load at 1/2/4/8 concurrent owners, separately from
   SQLite single-host local development; inspect database and object-store
   restoration after backup.
10. Measure live first-audio p50/p95/p99 over real user-network sessions.
    **No unconditional 400-ms TTFT guarantee is technically possible**.
11. Scan images/dependencies, isolate rendering processes, audit secrets,
    permissions, quotas, TLS and ownership, and review all external tools.
12. Produce a real evidence ZIP: trade-research/financial scenarios and the
    market scenario, each with actual generated native artifacts and source
    records. A green synthetic test is never a live qualification.

## How to run actual V17 acceptance

```bash
pip install -e '.[work,deepagents,test]'
export RIZZLER_AGENTIC_ENABLED=1
export RIZZLER_WORK_ORCHESTRATOR=deepagents
export RIZZLER_WORK_LLM_BACKEND=sglang
export RIZZLER_SEARCH_BACKEND=searxng
export RIZZLER_ARTIFACT_QA=agentic
# Configure local SGLang/SearXNG endpoints and private credentials.
python scripts/qualify_mvp.py --output /tmp/rizzler-v17-live --stock-market
```

The output evidence ZIP is `/tmp/rizzler-v17-live/MVP_ACCEPTANCE_REPORT.zip`.
This runner never asserts an external system worked when it did not: if the
required jobs fail or files are missing, it exits with a nonzero code.

**Remaining architecture gap:** the currently used opt-in encrypted memory is
not yet the requested enterprise-grade Mem0/Qdrant lifecycle. LangGraph uses
WorkStore receipt-based crash replay, not a separately qualified distributed
LangGraph PostgreSQL checkpointer. Independent claim-level factual truth is not
established merely by matching a number to a downloaded excerpt. Full live
integration, performance, quality and failure matrices remain mandatory.
