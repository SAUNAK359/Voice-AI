# Rizzler V10 — Specialist Work Agent runtime and quality contract

## Architecture and boundaries

```
Voice Agent (Whisper → Gemini → KittenTTS; independent low-latency lane)
  ↕  [future external A2A interface; not implemented in this change]
Work Agent API (owner-scoped request admission, cancel, status, downloads)
  ↓ durable parent job + fencing lease
Work Worker (independent async service, bounded queue and heartbeats)
  ↓ deterministic dependency-aware local agent plan
  ├─ Deep Research specialist, if requested
  ├─ SQL Analytics specialist, if a dataset is attached
  ├─ Content Orchestrator, unless research already produced a draft
  ├─ PowerPoint specialist → PPTX
  ├─ Word specialist → DOCX
  ├─ Excel specialist → XLSX / CSV
  ├─ PDF/Visual specialist → PDF / PNG / SVG / JSON / MD / HTML / TXT / ZIP
  └─ Quality gate → verified final output publication
        ↕ shared WorkStore transactional record + owner + SHA256 artifacts
     User progress events → status/SLA dashboard
```

Specialists run as isolated logical agents in the worker process; they do **not**
spin up six independent LLMs or six A2A servers. They follow bundled
`agent_skills/<specialist>/SKILL.md` operating procedures and use existing
format-specific tools. Native A2A/MCP wire servers are **not** implemented yet.
This avoids unnecessary network hops and inference duplication.

## Durable job state and recovery

The parent `jobs` table retains owner, request fingerprint, idempotency token,
attempt count, cancellation, lease owner, expiry, fence and terminal state.
The new `agent_steps` table stores one row per `(job_id,agent)` with:
- `status`: running / completed / failed
- `attempt` counter, start/end timestamps, last update and target deadline
- `result_json`, SHA256 over the committed checkpoint JSON, QA result and
  bounded error category

The existing parent fencing token is checked **inside every agent-step
transaction**. A restarted worker can read completed steps but must verify
their JSON hash and each output file hash before reuse. On lease expiry, old
workers cannot commit. Incomplete steps re-run after recovery and may create
duplicate external Gemini charges, never an unapproved completed artifact.

Intermediate files live under the owner/job-specific private checkpoint
directory; the final `WorkStore.finish()` remains the only publisher to the
artifact inventory. Do not delete checkpoints while a job can restart.
Implement a separately supervised TTL cleanup and durable backup procedure
before enforcing retention at scale; cleanup must never delete active jobs.
On Colab/Kaggle ephemeral storage these guarantees last only until runtime
reset. Production requires persistent volumes and real backup/restore drills.

## Async and cancellation policy

Jobs execute off the voice request path in the existing async worker process.
Long-running specialist calls are async or offloaded to threads, with a single
worker heartbeat that renews its parent job lease. A spoken interruption must
not cancel an independent Work Agent job; only explicit job cancellation does.
Independent jobs may be processed by separate supervised workers. The current
per-job plan runs dependent specialist steps in sequence. Subagent parallelism
should be enabled only for proven-independent tasks and after testing
concurrent quota consumption, memory and model/renderer thread safety.

## SLA targets and telemetry (proposed, not contractual)

| Agent | Alert target |
|---|---:|
| Grounded research | 180 s |
| SQL analytics | 60 s |
| Content orchestrator | 150 s |
| PowerPoint | 120 s |
| Word | 90 s |
| Excel | 120 s |
| PDF/visualization/packaging | 120 s |
| Master QA | 45 s |

The API `GET /api/work/jobs/{id}/agents` returns persisted attempts,
start/finish times, status, deadline, QA checks and computed target state.
`met` is derived from the stored end time; `overdue` is derived from the
clock, not an invented percentage or estimated completion time. These values
are **stage timing targets**, not whole-job response-time SLAs, nor evidence
of external availability or GPU throughput.

## Quality policy and fail-closed results

- **Research:** actual provider-returned HTTPS grounding sources and
  substantive content. Unsupported or outdated claims need live source audit.
- **SQL:** bounded CSV/XLSX, read-only in-memory SQLite, real counts reconciled
  with independent deterministic profiling; no arbitrary DB privileges.
- **PPTX/DOCX:** actual editable artifacts, OOXML ZIP/CRC structural verification
  and stable SHA256 receipts. Independent visual rendering and design checks
  remain mandatory before a superior-quality claim.
- **XLSX/CSV:** source-derived tables, formula-injection escape, valid archive
  structure. No claim of Excel formula recalculation without a calculation engine.
- **PDF/PNG/SVG:** real renderers; numeric charts require actual dataset input.
- **ZIP:** must contain preverified outputs and its own manifest/checksum.
- **Master QA:** checks every requested deliverable, no duplicate or extra
  receipts, file bytes, structural validity, evidence lineage and SQL
  reconciliation. Failure means **no COMPLETED parent job**.

A model's confidence is never final evidence. The parent WorkStore commits
only after deterministic QA. Live semantic/factual checking, slide rendering,
spreadsheet recalculation, accessibility and formal hallucination evaluation
are still needed for a complete production quality score.

## Honest comparison to Claude

A statement that Rizzler's specialist work *beats Claude* requires a blinded,
task-matched benchmark with fixed datasets, the same source permissions,
identical quality rubrics, independent graders and measured cost/latency.
Compare at least: research citation validity and coverage, SQL numerical
accuracy, PPTX visual quality, DOCX content completeness, XLSX formula
recalculation, tool recovery rate, artifact integrity, total turnaround and
resource cost. Record failed runs in denominators. There is no evidence of
comparative superiority from passing this repository's CI tests alone.

## Voice persona change

The Gemini system prompt now asks for energetic, vivid, warm, concise natural
speech with appropriate uncertainty and zero fabricated work claims.
KittenTTS uses bounded per-phrase speaking-rate adjustments based on
punctuation. This provides lightweight rhythm variation, **not** true
emotion-conditioned speech synthesis. A more expressive TTS provider would
require independent acoustic quality, intelligibility and latency tests.

## Qualification and release gates

1. Python 3.11/3.12/3.13 tests and GitHub workflows pass on the exact commit.
2. The six `SKILL.md` files ship in the installed application package.
3. Parent job and specialist states survive reconstruction of WorkStore and
   lease replacement, with failed SHA checks rejecting corrupted checkpoints.
4. Stale worker updates, cross-owner status reads and non-read-only SQL fail.
5. All twelve file formats remain generated and structurally validated.
6. Every agent reports meaningful timestamps/QA and no false SLA guarantees.
7. Real Gemini, OIDC, PostgreSQL, S3, live TTS prosody and actual PDF/PPTX
   visual evaluation are qualified separately before calling it production-ready.

No completed stage, job, artifact or SLA is inferred from an LLM narrative.
