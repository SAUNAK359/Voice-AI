# Rizzler V23–V24: Cognitive Work System implementation contract

**Status:** staged implementation plan; a phase is not complete until its acceptance gates pass.  
**Baseline:** `SAUNAK359/Voice-AI` V23.1 feature branch; existing code still contains V11 preview limitations.  
**Non-goal:** unrestricted model access to the network, secrets, production deployments or other users' data.

## Core invariants (apply to every phase)

1. The model owns **semantic decisions** (scope, relevant domains, hypotheses, research strategy, content architecture, tool choice, repair priorities). It never grants itself **authorization**.
2. Typed schemas, allowlisted capabilities, transaction fences, owner checks, network isolation, timeouts, resource budgets, idempotency and proof obligations are enforced in code. These are *contracts*, not keyword-based intelligence.
3. Every conclusion carries evidence IDs, computation receipts, uncertainty or a label marking it as interpretation. Provider search grounding alone is **attribution**, not proof that a page was verified.
4. Every irreversible or external-write action requires scoped approval; no tool output is treated as an instruction.
5. Cross-agent awareness is an append-only, owner-scoped **public finding/event stream**; no opaque model chain-of-thought is stored or transmitted.
6. Fast path: one specialist and minimal model calls for low-complexity tasks. Long path: adaptive decomposition and bounded parallelism for high-value independent research branches. Avoid idle coordination calls.
7. Completion means **task requirement coverage**, evidence fidelity, structural checks, rendered inspection where available, numerical reconciliation and explicitly declared unsupported claims. No false “100% accuracy” or no-503 guarantees.
8. Each release must preserve testable behavior on mock/offline environments and be deployable by toggling a versioned, documented setting; incomplete research and provider outages produce recoverable/partial states, not fabricated output.

## Stage 0 — audit and execution contract

**Inputs:** the authenticated Work handoff; desired formats; uploads; previous work.  
**Outputs:** immutable `WorkStore` job, approved DAG, owner-scoped idempotency key, leased worker; baseline latency/QA metrics.
- Audit `work_agents`, `work_specialists`, `work_worker`, `work_store`, `work_ir`, `work_design`, `work_quality`, `work_api`, `research_evidence`.
- Track baseline: number of original findings, claim support ratio, research depth, slide repetition, page occupancy, p50/p95 time, budget, model failures and restarts.
- Preserve the WorkStore fence/lease/checkpoint model; do not replace it with in-memory LangGraph state or a separate inconsistent queue.
**Gate:** full existing tests pass, V23.1 hierarchy tests pass, no authorization regressions.

## Stage 1 — dynamic cognitive director and inverse-pyramid planning

**Tasks:** Model infers objective, audience, constraints, requested formats, required evidence and deliverable-specific depth. Creates broad-to-specialized `StageBrief` contracts; dynamically branches domain/subdomain/expert tasks, with explicit stop conditions and uncertainties.
- Typed charter / `TaskTree`: task ID, parent, depth, purpose, approved specialist, dependencies, proof required, missing information, budget and expected deliverables.
- Model-generated stages must be schema validated and scoped to user-approved tools; no code path routes using static domain keyword maps.
- Complexity-adaptive routing: simple tasks do not trigger elaborate subagents; complex work gets parallel **independent** decomposition, not gratuitous agent count.
- Replanning is versioned, reasoned and constrained; never mutates previously authorized external effects.
- The current V23.1 static approved DAG remains **execution authority** until dynamic DAG migrations and recovery are verified.
**Gate:** held-out tasks across five unrelated domains; scope preservation, prompt-injection resistance, new-domain generalization, restart-safe plan versions.

## Stage 2 — source acquisition and evidence operating system

**Tasks:** Model proposes research questions and multiple authoritative source paths. Acquisition adapters fetch approved material with network egress controls, typed limits, provenance and independent metadata.
- Structured extraction routes: HTML `trafilatura` with fallback HTML parser; Markdown headings/tables; PDF text/tables with page references; CSV/JSON and uploaded Excel via bounded reader; OCR/VLM for image-only pages as an explicit optional tool with confidence disclosure.
- `SourceDocument`: URL/content hash, acquisition time, publisher, effective date when known, content type, section IDs, page numbers, tables, extraction quality flags and warnings.
- Reject/flag: inaccessible pages, empty fragments, JavaScript shells, paywalls, unsupported types, duplicate/corrupt content, oversized tables, contradictory date units and poisoned instructions. Fail over to independent sources or report a gap.
- Fetch from untrusted URLs only through a network-restricted service or sandbox with no access to link-local/private/cloud-metadata addresses. Public URL validation alone is **not sufficient SSRF protection**.
- Separate **source attribution** from independently retrieved source text; citations must identify which assertion is actually supported.
**Gate:** malformed HTML/Markdown/PDF fixtures; oversized/redirect/private-address rejection; page and table provenance; fresh-source and numerical cross-source tests.

## Stage 3 — shared cognition + adaptive context compiler

**Tasks:** Every specialist publishes concise, versioned task-level findings, gaps, decisions and artifact statuses to a durable owner/job-scoped ledger.
- Append-only ledger with atomic writes in the existing WorkStore transaction. Event types `finding`, `gap`, `artifact`, `verification`, `state`. Each includes producer, correlation ID, SHA-256, timestamp and approved reference IDs.
- Read-after-write and monotonic cursor; consumers receive **only relevant summaries** at their next tool or checkpoint boundary. No requirement to broadcast a whole multi-megabyte context to all agents.
- Conflict checks are explicit: opposing findings coexist and are resolved by evidence, not last-write-wins. Independent sibling agents write in parallel.
- Rebuild current task context from ledger after crash. Surface owner-scoped event stream via authenticated Work API. Voice uses concise status summaries, not raw private source material.
- Optional semantic/episodic/procedural stores can be added later, but validated evidence is never replaced by unsupported memory.
**Gate:** 30+ concurrent writers, monotonic sequences, owner isolation, tamper detection, replay after restart, low overhead under 3-slot inference scheduling.

## Stage 4 — expert reasoning and evidence-aware content intelligence

**Tasks:** Domain experts independently derive findings, calculations, counterarguments and missing evidence; the director builds a **Content Coverage Ledger** before file generation.
- Planner returns schema-checked `ContentPlan`: question, required evidence, analytical operations, domain review, estimated space, sections and cross-format dependencies.
- Parallel subtask writers produce sections from controlled evidence summaries. A synthesis and contradiction gate reconciles them. Detailed content is created once, but each file gets its own blueprint.
- Reader-facing artifacts contain reasoning **results, methods, and verifiable calculations**, not raw hidden model deliberation.
- On unsupported factual tasks, research instead of inventing statistics. Missing/blocked evidence remains a clearly labeled limitation and can block final qualification.
- Cost/latency: selective expansion by expected information gain; dynamic per-task budget; independent drafts parallel; no unnecessary “agent discussions”.
**Gate:** section/question coverage, non-repetition, contradiction detection, causal claims challenged, numerical facts reproducible, stronger artifact quality than V23.1 evidence ZIP.

## Stage 5 — universal capability fabric and programmable tool execution

**Tasks:** Model selects from runtime-discovered authorized MCP skills, read-only SQL, charts, code execution and renderers. Tool compiler validates inputs and data flow before execution.
- Capability manifests: schema, trust level, side-effects, timeout, idempotency, owner scope and availability.
- Narrow sandbox; bounded CPU/RAM/walltime/network; no unrestricted shell or URL execution from model text.
- Task-specific micro-specialists and reusable snippets are ephemeral. Tool results are typed evidence and may carry untrusted text.
- Use a single authorization system; no independent internal agent can escalate permissions.
**Gate:** cross-tool execution, permission denial, sandbox escapes rejected, failures captured, idempotent retries and cancellation.

## Stage 6 — format-specific artifact production

**Tasks:** Independent design agents use validated `ContentPlan` and `ArtifactIR` to create distinct, substantive outputs.
- PPTX: meaningful per-slide hypotheses and evidence, editable charts/diagrams, captions, references, title fit, presenter notes, layout consistency; avoid Markdown tokens and automatic filler slides.
- DOCX/PDF: substantial report structure with methodology, sections, citations, tables, exhibits, limitations and readable pagination.
- XLSX/CSV: original data, units, formulas, provenance, named tables, numeric reconciliation, dangerous formula-string escaping.
- Each segment has input/output hashes so only changed findings cause rebuilds. Preserve verified unaffected outputs.
**Gate:** semantic coverage + visual render pass + structural integrity + cross-artifact consistency; independent content for each medium.

## Stage 7 — independent qualification, targeted repair and release

**Tasks:** Challenge source support, expert correctness, numbers and design. Pin a reproducible **claim/evidence/section/artifact** dependency graph.
- AI reviews produce typed findings with a severity and exact artifact location, while deterministic checks verify files, formulas and overflow where measurable.
- Reopen the **upstream cause** (research gap, wrong calculation, unsupported conclusion, weak slide/layout); rerun only affected descendants. Cap repair loops and publish uncertainties honestly.
- Required release qualification: offline tests, fault-injection (503/429/network reset, crash, partial file), GPU/browser paths when relevant, strict visual QA, data reconciliation and independent human inspection of a benchmark sample.
- Compare blinded, held-out complex tasks against a Claude-based baseline; report actual metrics, not anticipated superiority.
**Gate:** all mandatory checks passing, no critical unsupported claims, quality targets met on held-out fixtures, latency/cost reporting and deployment rollback readiness.

## Phase dependencies and anti-regression policy

Stage 3 ledger and Stage 2 source normalization may be delivered independently first. Stage 4 requires their typed artifacts; Stage 6 requires content plans; Stage 7 makes those outputs trustworthy. A new subagent may inform another by publishing a validated finding to the ledger while both run, but must not directly mutate the sibling's state. A completing work agent must not announce success when artifacts are only structurally valid.

## Immediate incremental implementation

1. Introduce bounded, structured source normalization for HTML/Markdown/JSON/CSV/PDF bytes, preserving provenance and extraction warnings.
2. Add a durable **cognitive event ledger** to WorkStore, with owner-scoped authenticated reads and fenced writes.
3. Wire agent checkpoints to publish and consume compact context deltas, without changing existing external permissions.
4. Introduce a model-directed research/content-plan API and test against both mocked providers and live Gemini behind opt-in qualification.
5. Before release, verify full existing suite, run Kaggle evidence ZIP comparison, and validate strict visual QA plus injection/503 tests.

**Operational truth:** Provider outages, blocked sites, corrupt external documents and unsupported user requests cannot be guaranteed never to fail. The application must contain failures, retry with bounded policy, choose valid alternatives when possible, and expose partial/blocked state rather than silently invent facts.
