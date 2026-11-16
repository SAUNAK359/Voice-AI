# Rizzler V16 implementation and release plan

## Implementation checkpoint

This branch is **NOT PRODUCTION QUALIFIED**. It is an incremental working
migration, not a completed deployment.

Committed V16 components:
- Deep Agents + LangGraph planning adapter with model-authored validated DAGs,
  opt-in via `RIZZLER_WORK_ORCHESTRATOR=deepagents`.
- Preserved original owner-qualified WorkStore leases, checkpoints and
  artifact publication; bounded provider 429/5xx deferral now persists
  next-attempt timestamps rather than creating duplicate jobs.
- Private SearXNG JSON discovery, DNS-pinned direct HTTPS retrieval and
  direct-fetch provenance, paired with local SGLang reasoning.
- Live controller instructions distinguish task submission from standalone
  search, but successful live voice handoff is still unverified.
- Same encrypted, opt-in owner memory is now readable by the Work Agent
  as **untrusted preferences**, not automatically retained external facts.
- Docker image optional framework dependencies installed; single-host
  private SGLang/SearXNG Compose overlay and CI configuration checks.
- Offline regression contracts for invalid DAG repair, keyless search
  configuration, owner-isolated shared memory and fenced provider retry.

Unimplemented or not yet validated:
- Full dynamic tool-using Deep Agents across every specialist (current runtime
  delegates graph authoring, then reuses existing vetted executor).
- Mem0/Qdrant semantic long-term memory, provenance-aware source claim
  verification, structured sourced web-to-Excel ingestion, sophisticated
  PPTX layout and artifact-design repair.
- Actual GPU-backed SGLang tool calls, self-hosted SearXNG live search,
  Gemini Live user handoff, load/fault injection, backup/restore, and
  full downloadable multi-artifact package review.
- No measured or guaranteed 400 ms Gemini Live audio TTFT.

**Deployment instruction: do not merge or deploy as production until P0–P6
release gates below are backed by logs and downloadable artifacts.**

## Repository audit / baseline

Source of truth: the V15 implementation at `b6bd61c1`, reviewed against
`Rizzler_V15_Colab_E2E_Evidence.zip`.

- **Voice:** `api.py`, `agent_runtime.py`, `live_native.py`, `voice_tools.py`.
  Gemini Live is separate from the background Work reasoning model.
- **Durable execution:** `work_store.py` / `work_postgres.py`,
  `work_worker.py`, `work_specialists.py`. Job claims and artifact
  publication are fenced by owner and lease.
- **Previous planning:** `work_dynamic.py`, `work_preflight.py`,
  `work_cognition.py`. Models frequently produced invalid plans in live tests.
- **Sources and tools:** `source_links.py` pins TLS/DNS for URL ingestion;
  `work_mcp.py` is an owner-scoped stdio control-plane bridge.
- **Outputs:** `work_ir.py`, `work_presentation.py`,
  `work_skills.py`, `work_quality.py`, `work_repair.py`.
  These contain useful native artifact execution but need content and design QA.
- **Memory:** `memory.py` is an opt-in encrypted private store,
  not a shared multi-agent semantic-memory service.

### Reproduced user acceptance findings

- Offline synthetic scenarios: 2/2 completed.
- Live acceptance: 0/2 completed (provider ServerError before specialist plan).
- Extended Indian imports/exports: invalid invented SQL dataset on all three
  cognitive-preflight attempts, zero published artifacts.
- Voice-to-Work: voice used `research.search` and never submitted a Work job.
- Full Colab test session: 25 failed / 380 passed / 1 skipped; test isolation
  was compromised by globally enabled live settings.
- Release inventory: outdated manifest checksum for `work_api.py`.
- Rendered synthetic slides cannot establish design or live factual quality.

## Target boundaries

```text
Gemini Live (conversational, interruption-friendly)
   -> authenticated submit + original user request preserved
   -> owner-scoped WorkStore job + durable receipt
   -> Deep Agents / LangGraph reasoning model (local SGLang or configured Gemini)
   -> validated specialist DAG + checkpointed work
   -> SearXNG -> pinned HTTPS source acquisition / structured data
   -> existing native artifact renderers -> independent QA / repair
   -> verified artifacts + progress events -> Live Agent and private Studio
```

**Single state authority:** WorkStore owns job lifecycle, ownership, cancellation,
fenced stage receipts and final output. LangGraph state is transient planning
scratch state until a shared durable checkpointer has been qualified. No second
autonomous queue or unrestricted host filesystem access is introduced.

**No hard-coded task routing:** The LLM chooses the specialist graph and
medium/high planning tier. Backend contracts still validate permissions,
required tool dependencies, data lineage and publication integrity.

**Keyless tool limitation:** SearXNG and Playwright can run without subscription
keys, but public pages can throttle or block clients. Reliable stock-exchange
opening/closing figures may require licensed feeds. Gemini Live itself requires
authenticated Google access. No provider/host can guarantee 400-ms end-to-end
TTFT; measure P50/P95/P99 under realistic network conditions.

## Implementation phases and exit gates

### P0 — Baseline and regression correctness
- Isolate test configurations, pin provider versions, restore inventory
  manifests after modifications, never run paid calls in offline CI.
- Gate: Python 3.11–3.13, JS, production config, security scan green at exact
  final SHA; production backup/restore and secrets review.

### P1 — Deep Agents integration (branch implementation started)
- Add optional `work_deepagents.py`, select
  `RIZZLER_WORK_ORCHESTRATOR=deepagents`.
- Deep Agents executes on LangGraph; an allowlisted plan submission tool calls
  the existing `work_dynamic.validate` and returns specific corrections.
- Keep stage execution and artifact commit in WorkStore; prohibit arbitrary
  model-driven API/file/shell writes.
- Gate: invalid submitted-dataset graph rejected, valid no-dataset research
  graph accepted, exact job receipt survives restart.
- **Current state:** code committed; dependency/runtime CI still unverified.

### P2 — Live handoff and tool semantics (partially started)
- Voice model retains natural speech and may submit a structured job through
  `work.submit`; Work owns research, analytics and artifacts.
- Persist original request plus interpreted constraints, immutable deliverable
  list, source policy and idempotency key.
- Gate: voice and text must each create exactly one owned job for an artifact
  request; Rizzler remains available during Work; never claim completion early.
- **Current state:** controller instruction improved; live acceptance pending.

### P3 — Keyless source discovery + claim provenance (partially started)
- Self-host SearXNG for discovery; retrieve public pages via DNS-pinned HTTPS.
- Model selects searches, treats fetched content as untrusted, stores source
  timestamps/links and reports incomplete evidence.
- For high-stakes facts, add claim-excerpt matching and independent numerical
  reconciliation with dates and units; do not equate source attribution with
  factual verification.
- Gate: 20 official-source test cases, redirects/SSRF/prompt injection,
  unavailable search servers, market-session calendar edge cases.
- **Current state:** keyless adapter committed, not live qualified.

### P4 — Memory and distributed state
- Evaluate Mem0 OSS + local Qdrant in an owner-scoped private gateway; compare
  against existing encrypted memory before migrating.
- Separate ephemeral conversation, Work checkpoints and verified long-term
  memories. Version entries, provenance, expiry, deletion and contradiction
  reconciliation. Never turn unverified web content into user memory.
- Run Postgres checkpointer and WorkStore transaction invariants against
  concurrent workers; do not create an independent second queue.
- Gate: cross-owner tests, deletion/retention tests, recovery across restarts.
- **Current state:** encrypted shared-memory bridge implemented; Mem0 migration and semantic-memory qualification remain unimplemented.

### P5 — Native artifact intelligence
- Data-first typed table/schema layer; DuckDB and formula validation.
- Improve PPTX/Word/PDF layout engine, charts, table visualizations,
  editable output; render every page with LibreOffice/PyMuPDF.
- Iterative specialist critique and bounded repair; keep missing-evidence
  state visible rather than fabricating facts.
- Gate: actual Indian trade research to PPTX/DOCX/XLSX/PDF/ZIP and
  stock-market weekly OHLCV with accurate source dates.
- **Current state:** V15 native renderers preserved; quality upgrade pending.

### P6 — Production qualification
- Inject provider 429/5xx, timeouts, subprocess crash, stale lease, network
  partition, malformed source file and job cancellation mid-render.
- Measure 1/2/4/8 concurrent owners and queue throughput, GPU utilization,
  p50/p95/p99 model response and first audio latency.
- Require source-aware editorial review of final rendered artifacts.
- Perform backup/restore, OIDC login, malware scanning, TLS, secret rotation,
  rate/quote controls and actual one-host deployment validation.
- Gate: no unowned artifacts, no duplicate publication, all critical gates
  passed and downloadable acceptance ZIP inspected.
- **Current state:** not passed. DO NOT DEPLOY as production-ready.

## Configuration

```sh
pip install -e '.[work,test,deepagents]'
export RIZZLER_AGENTIC_ENABLED=1
export RIZZLER_WORK_ORCHESTRATOR=deepagents
export RIZZLER_WORK_LLM_BACKEND=sglang
export RIZZLER_SGLANG_MODEL='your-qualified-tool-calling-model'
# Configure private SGLang and self-hosted SearXNG separately.
export RIZZLER_SEARCH_BACKEND=searxng
export RIZZLER_SEARXNG_URL=http://127.0.0.1:8081
```

Opt-in switches preserve the existing V15 path for comparison; production
should only enable V16 after real connected acceptance, not based on mocked
unit tests alone.
