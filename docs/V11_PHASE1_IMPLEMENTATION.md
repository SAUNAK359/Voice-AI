# Rizzler V11 — Phase 1 Implementation and Qualification

**Status:** implemented on the Phase 1 feature branch; independent live-provider evaluation is a separate release gate. The existing V10 WorkStore and six specialists remain authoritative.

## User-visible result

Rizzler can accept a multi-deliverable task such as **“Research EV competitors and create a PowerPoint and PDF report.”** The Voice Supervisor identifies the explicit private-work request, optionally uses one bounded Gemini classification call, then submits to WorkStore with an immutable validated execution graph. Rizzler acknowledges only once WorkStore commits the job. The same conversation displays the persisted plan, specialist status, and verified artifact links. A slow planner may receive a neutral spoken acknowledgement (“I will organize the work into verified steps”) before work has been accepted; that acknowledgement is **not** a completion claim.

Simple greetings, ordinary Q&A, exact local arithmetic and clear single-tool requests do not call the planning model. The Work Agent runs independently of voice interruption.

## Source code and contracts

| Area | Owner / file | Contract |
|---|---|---|
| Tool registry | `src/rizzler/tool_registry.py` | Version 1, risk, timeout, input fields, configured state |
| Scope advisor | `src/rizzler/task_planning.py` | At most two constrained JSON responses, 7 s per attempt; model cannot add unrequested scopes |
| Approved DAG | `execution_graph()` | ≤12 unique nodes, acyclic, trusted tool identifiers and explicit dependencies |
| Atomic persistence | `src/rizzler/work_store.py` | `job_plans` row committed with job and specialist rows; hash verification and owner isolation |
| Execution | `src/rizzler/work_specialists.py` | Existing lease/fence/heartbeat/QA, with persisted prerequisite checking |
| Live research | `src/rizzler/work_worker.py` | Up to two complementary grounding requests; failures retained as partial |
| Evidence | `src/rizzler/research_evidence.py` | HTTPS URL vetting, provider citation IDs, source title, publisher and retrieval time |
| Voice control | `src/rizzler/voice_tools.py` | Trusted permission gateway and bounded job dispatch |
| UX | `src/rizzler/web/app.js` | Live job cards and approved workflow within conversation |

The graph uses canonical node IDs (`research`, `sql_analytics`, `orchestrator`, `powerpoint`, `word`, `excel`, `pdf_visual`, `quality`). Evidence acquisition is independent, report generation depends on evidence, packaging follows required documents, and QA depends on all prior stages. Concurrent specialists retain the existing two-agent semaphore to protect live voice performance.

Every graph node has `id, tool, depends_on, version, risk, target_seconds`. The graph is stored with an SHA-256 digest. Tampering, unknown tool names, inconsistent risk declarations, renamed steps or invalid dependencies block execution. Older jobs fall back to a deterministic derived graph without being silently rewritten.

### Policy boundaries

- Read-only search and math: no external write approval needed; provider quota still applies.
- User-commanded private artifacts: authorized only for the authenticated owner and explicit creation intent.
- Cancellation: only explicit owner command; speech interruption never cancels background Work.
- External sends/shares/deletes/payments/GPU acquisition: **not exposed** by the Phase 1 tool registry. No LLM-generated text can grant permission.
- Model proposal can advise the need for explicitly requested research/analysis but cannot invent deliverable formats, owner IDs, file references, external actions or privilege scopes.
- Inputs and model responses are bounded. Invalid JSON gets one correction opportunity, then explicit-user-scope deterministic fallback. If no safely derivable scope exists, no additional work is created.

### Research trust and caveats

The Work research specialist makes two independent *provider-grounded* queries (primary evidence and challenge/counterevidence). They run concurrently within the Work lane and are capped. If one perspective fails, the report identifies the coverage gap; if both have no sources, research fails and QA refuses a completed job.

The evidence record includes a canonical safe HTTPS URL, provider-attributed publisher/title, retrieval timestamp and an explicit `content_verified: false`. It does **not** claim to have fetched and read the source webpage. URLs with local/internal endpoints, IP literals, userinfo, invalid schemes, unsafe ports and malformed hostnames are excluded. This release intentionally does **not** fetch arbitrary third-party URLs, because a naive HTTP crawler would introduce server-side request-forgery and prompt-injection risks.

Provider grounding is *not* independent proof that individual claims are supported. Full webpage extraction, author/publication timestamp verification and independent claim-to-source scoring remain distinct future qualification work. Live financial quotes must disclose quote time/provider or remain unverified.

## Failure and recovery acceptance

| Injection or failure | Required observed behavior |
|---|---|
| Unsupported model tool / external action | Reject via closed registry before effect |
| Malformed planner JSON | One correction; deterministic explicit-request fallback |
| Planner tries new research scope | Reject model-suggested escalation |
| Negated research request | Do not add a research stage |
| Missing dataset | Request upload; never substitute invented data |
| Source URL targets private network | Exclude URL; never perform fetch |
| Only one research response usable | Label challenge coverage incomplete; preserve grounded output |
| Both provider calls fail | Research stage fails; no verified parent completion |
| Worker restart / expired fence | Reuse SHA-verified committed steps; stale worker cannot publish |
| Tampered immutable graph | Integrity error blocks Work execution |
| Unauthorized owner reads job/plan | Return not found |
| Parent cancelled | Persist cancellation and settle pending specialist states |
| Rendering or QA fails | No completed artifact inventory published |
| Multi-output request | Persist explicit dependency graph, not a model-only promise |

## Test and proof

`tests/test_v11_phase1.py` exercises tools/risk policies, multiple DAG shapes, malicious modifications, owner isolation, idempotency, JSON repair, model-permission escalation, negative instructions, unsafe source URIs, provenance and an end-to-end stubbed Work job. The existing application, PostgreSQL, browser and security tests must remain green.

The frozen `benchmarks/fixtures/tool_routing_v11.jsonl` contains 50 hand-curated utterances across ordinary conversation, grounded search, symbolic math, private Work submission, status and cancellation. Run `python scripts/evaluate_tool_routing.py` for a transparent confusion matrix. This fixture is a regression suite, **not** a statistically representative 300-utterance real-user benchmark.

### Live qualification still required

1. Run the exact merged source commit with real Gemini Search grounding, including 429/503/rate-limit handling and fresh source metadata.
2. Perform ≥30 legitimate search/research tasks and an independent factual citation audit.
3. Freeze ≥100 real multi-step scenarios; evaluate full task completion and no unnecessary tool calls.
4. Evaluate a diverse human-labeled ≥300-utterance routing set for precision, recall and no unauthorized effects.
5. Execute runtime restart/kill/replay trials on persistent PostgreSQL plus object storage.
6. Measure warm/cold voice first-audible and model TTFT separately, including errors and resource costs.
7. Validate end-user behavior on the actual Colab T4 demo and supported durable production environment.

Passing mocked CI checks **does not certify** live source truth, provider/model entitlement, external uptime, production SLAs, or competitive superiority.

## Activation and rollback

For the existing install: configure `GEMINI_API_KEY` in a private environment, and the existing `RIZZLER_WORK_ROOT` and `RIZZLER_WORK_SIGNING_KEY` for Work. Start the API and separate WorkWorker as documented in the repository. Only use persistent volumes for durable-production claims. The authenticated `/api/voice/tools` returns tool registry details; `/api/voice/jobs/{id}` and `/api/work/jobs/{id}/plan` return owner-scoped, integrity-checked plans.

Rollback: deploy the preceding pinned commit and stop creating V11 plans. The additive `job_plans` table has no destructive migration. Existing job receipts/checkpoints remain on the same persistent volume; do not delete them during rollback. Verify client-to-worker compatibility with a staging restart and completion drill before using in production.
