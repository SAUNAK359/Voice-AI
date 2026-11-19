# Rizzler V24 — Cognitive Context Convergence and Non-destructive Repair

## Status (19–20 November 2026)

**Draft implementation**. Not production-qualified. Based on PR55 pinned SHA
\`fbf70fad3e5366ba49ebe404197526439095c13a\`, with the evidence archive
\`Rizzler_V23_PR55_Evidence_20261119_181404_6f8e6e.zip\`.
Open PR56 against PR55. No merge/deployment recommendation until all release gates pass.

PR55 outcome: 12 PASS, 4 FAIL; live Work failed from
\`work_studio.py:44\` "Malformed slide objective" and a parallel Word
call was cancelled by an unrelated PowerPoint failure. The research scenario
remained running at the observation cutoff, not a diagnosed research crash.
A Word regression fixture expected a complete rewrite on its second model
call even though implementation now first attempts a targeted editorial
expansion. V24 updates that fixture to test the intended safety-preserving path.

## Non-negotiable architecture

1. **User authorization is the ceiling.** Model-delegated roles inherit
   owner-scoped permissions, never create new resource privileges. Private
   writes require existing WorkStore/tool-registry authorization.
2. **LLM decides semantic work.** Gemini identifies information gaps, domain
   methods, investigation requests, reasoning level, and candidate edits.
   Code only enforces JSON/schema, evidence, authorization, numeric,
   concurrency, storage and release invariants.
3. **Original task and approved evidence are authoritative.** Source claims,
   independent calculations and user-provided assumptions remain labeled.
4. **Backdelegation is convergence, not looping.** A later reviewer can
   reopen an authorized earlier research/SQL specialist. After newly validated
   evidence arrives it rechecks the task. Repeated requests are deduplicated.
   Exhausted budgets surface a gap rather than fabricated completion.
5. **No destructive repair.** Valid neighboring slides, section identifiers,
   citation URLs, bullets, numbers and source coverage are untouched.
   No slide is promoted without full revalidation.
6. **Isolation without false success.** Independent format jobs continue if
   a sibling fails. The parent job *still fails* when a required artifact
   is missing; successful specialist checkpoints remain available.

### Runtime flow

\`\`\`text
User intent / authorized formats / uploads
    |
    v
Existing immutable WorkStore plan + goal contract + cognitive director
    |
    v
Approved research / SQL investigations (in parallel)
    |
    v
Expert findings + synthesis + persistent WorkStore cognitive events
    |
    v
Context Intelligence Supervisor --> context coverage and gap questions
    |                                      |
    |                                bounded backdelegation
    |                                      |
    |                         prior approved research / read-only SQL
    |                                      |
    <--------- newly checked findings -----+
    |                      LLM reassesses new evidence
    v
Versioned artifact IR + context package (objective, claims, sources,
data digest, section lineage and evidence sufficiency)
    |
    +--> PowerPoint --> exact-field repair --> structural and visual QA
    +--> Word -------> editorial expansion --> structural and visual QA
    +--> Excel ------> source-backed studies --> formula/SQL reconciliation
    +--> PDF --------> editorial/visual QA
    |
    v
Complete WorkStore receipt set + final quality gate + truthful status
\`\`\`

### Context Intelligence Engine

**Implemented components:** \`work_context_intelligence.py\`,
\`work_specialists.py\`, existing \`work_outcome.py\`,
\`work_ir.py\`, \`work_store.py\`.

- Generates versioned context snapshots including objective, formats, goal
  requirements, summarized source sections, approved URLs, dataset digest and
  unresolved issues. A context digest captures the exact evaluated package.
- Asks Gemini for a **ready / investigate / blocked** decision, evidence
  coverage per obligation, and a bounded list of *specific* missing
  investigations.
- Reopens only already-authorized \`research\` or \`sql_analytics\`; cannot
  allow model-generated tool names or unapproved owner data. Fresh results
  undergo existing specialist gates and read-only SQL checks.
- Maintains earlier narrative and URLs while adding independent new findings.
  It never treats provider-grounding metadata as independent verification.
- Re-evaluates context after every evidence-backdelegation wave and records a
  private, owner-scoped, fenced cognitive ledger event.
- Each artifact model receives a bounded contextual brief with the same
  revision, requirements and source list; no specialist can rewrite the
  shared context contract.
- Explicit max convergence waves and duplicate-request protection prevent
  runaway agent calls. If unresolved, generation fails closed.

**Important limitation:** a pre-artifact convergence gate is implemented.
A general dynamic graph that invalidates and reruns already-committed
downstream artifacts, arbitrary database retrieval, cross-job durable
read/write of new context, and live user-question/resume UI are not yet
complete. A production upgrade must add explicit dependency/version
invalidation, on-disk replay with integrity receipts, and user-approved
continuations. No claim of complete N+1-to-N-2-to-N+2 runtime across
*all* artifact types is made by this draft.

### Cognitive Verification and Recovery

**Implemented components:** \`work_repair.py\`, \`work_studio.py\` and
existing DOCX editorial expansion.

- The PowerPoint validator identifies the precise affected slide field:
  title, message, or slide kind, with limits and observed lengths.
- Gemini proposes a JSON patch containing only permitted field replacement.
- Any change to unaffected slides/fields, bullets, section IDs, citations or
  numeric values fails. Numeric facts cannot be introduced, deleted or
  altered by the patch.
- The complete original storyboard and its provenance contract are checked
  after each candidate. Only validated output is rendered.
- JSON that never produced a usable storyboard may be regenerated from the
  original trusted artifact IR, not the previous model's presumed memory.
- Repair attempts are bounded and fail explicitly when safe preservation is
  impossible.
- DOCX editorial expansion preserves original content and citations.
  The regression fixture now models the correct \`expansions\` response.

**Further release work:** build per-medium field-diff repair adapters for
formulas, chart types, citations, page layout, PDF pagination, SQL
investigations and cross-document statistics. Each adapter must identify
dependency edges and perform independent semantic regression. No claim that
an LLM reviewer alone proves factual truth.

### Gemini-native capabilities

**Implemented V24:** \`gemini_native.py\` and an experimental integration in
\`work_worker.py\` for public research subtasks.

Gemini chooses an appropriate combination of Google Search, URL Context
(only for a named public URL), or server-side Code Execution for public
calculations, plus a reasoning depth. The Python SDK must actually expose
each tool type. The host validates the choice against the permitted tool
set. Google Search remains required for research provenance. These tools
have **no access to private local files**; their output cannot replace
independently fetched source bytes or independently executed read-only SQL.

This facility is not silently enabled. Tool combinations, billing,
response metadata and thinking levels differ among models. Test with
the *actual configured model ID*; do not infer support from names.

**Target production Gemini matrix (not all implemented):**

| Feature | Intended use | Implementation/qualification |
|---|---|---|
| Native Google Search grounding | Current public evidence | Existing integration; live retrieval qualification outstanding |
| URL Context | Public named-source analysis | Experimental capability selection; provider QA outstanding |
| Built-in Code Execution | Public technical calculations | Experimental selection; never used for private user SQL |
| Structured output | Stable specialist contracts | JSON generation and independent validators; strict native schemas need broader integration |
| Thinking levels | Dynamic specialist reasoning budget | Experimental native research; benchmark each actual model |
| Context caching | Reusable approved long evidence | Planned: versioned source cache, owner scoping, TTL, invalidation, cost audits |
| Long-context file/multimodal input | Mixed PDF/images/charts/audio | Existing ingestion partially available; native multimodal routing and OCR need qualification |
| Function calling and tool retrieval | LLM-selected MCP tools | Planned: role-scoped registry declarations and audited client execution |
| Context circulation/thought signatures | Preserve multi-turn function context | Planned: return intact provider response items, never forge signature contents |
| Streaming/Live API | Voice interruptions and feedback | Existing separate path; end-to-end synchronization still needs load/device testing |
| Managed agents/background API | Isolated long work | Separate design evaluation, not a substitute for WorkStore owner controls |
| Gemini fallback/resilience | 429/503 recovery | Existing provider retry/rate governor; real paid-tier resilience testing outstanding |

Native tools must not be enabled indiscriminately; capability requests
increase cost, latency, exposure, and sometimes reduce compatibility.
Privilege decisions and user confirmations remain host-authoritative.

### Modules to finish for actual production qualification

| Area | Concrete acceptance criterion |
|---|---|
| Dynamic graph/re-delegation | An artifact agent requests missing evidence *after* beginning; approved prior specialist fulfills it; changed dependency invalidates every impacted downstream output; resume is idempotent |
| Persistent context ledger | Signed/hash-checked, owner-scoped, versioned context and source receipts recover across process/fence restarts with no lost data |
| Cross-artifact consistency | Every shared measurement and unit reconciles across SQL, workbook, charts, slides, Word and PDF |
| Gemini capability broker | Provider metadata/feature probing, failure-aware downgrade, cost/latency budgets, tool response validation, no private access leaks |
| Research | HTTPS verified source retrieval, primary citations, exact quoted claims, conflict handling, bounded retries and stale-fact tests |
| Databases | Authorized connectors and dialect-aware read-only investigation; separate explicit approval for writes; avoid unrestricted remote SQL |
| PowerPoint | Sophisticated editable layouts, visual audits, evidence-linked slides, targeted correction and regression QA |
| Word / PDF | Publication-grade editorial/semantic checks, page boundaries, figures, accessibility and citation mapping |
| Excel | Financial/stats models, native formulas, calculations, charts, editable output and independent formula correctness |
| Tools / MCP | Per-owner credentials, scopes, sandboxing, signature validation, actual read/write policy and auditable redaction |
| Live voice + Work | Task handoff, progress events, interruptions, cancellation, owner identity and artifact preview sync |
| Operations | 429/503 circuit breaker, distributed rate controls, checkpoint recovery, cost caps, chaos/soak tests, tracing and alerting |

### Feature rollout and tests

Keep these experimental features disabled by default, including under
\`RIZZLER_V23_MODE=full\`, until provider and artifact qualification:

\`\`\`text
RIZZLER_CONTEXT_CONVERGENCE=1
RIZZLER_GEMINI_NATIVE_TOOLS=1
RIZZLER_GEMINI_ENABLE_THINKING=1
\`\`\`

Before enabling all three on real user work:

1. Pass minimal Python CI, all Work extras, strict visual/structural QA,
   source integrity, frontend App CI and CodeQL.
2. Pass mocked N+1 -> N-2 -> N+2 evidence tests and malicious/invalid
   tool-delegation tests; verify no user permissions have expanded.
3. Run the actual pinned PR56 notebook/source against paid Gemini:
   search, SQL, PowerPoint, Word, Excel, PDF and combined mixed outputs.
4. Inject provider timeouts/429/503, invalid JSON, unsupported tool combos,
   unsupported thinking config, interrupted workers and stale leases.
   Require recovery or clear actionable failure, not false success.
5. Manually compare rendered pages/charts to data and inspect factual
   correctness, accessibility, numerical consistency and editorial depth.
6. Test independently owned data, private upload isolation, adversarial
   prompt injection, malicious URLs and SQL read-only boundaries.
7. Validate end-to-end latency/cost/load and downgrade behavior on the
   intended hardware/cloud configuration.

**Ship rule:** CI success is necessary, not sufficient. In particular,
without an authenticated live Gemini run, successful visual QA of native
artifacts, cross-agent dependency invalidation and persistent context
resume, this V24 PR remains **draft / not production-qualified**.
