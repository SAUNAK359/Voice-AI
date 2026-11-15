# Rizzler V13 — MVP Release Qualification

This is the acceptance contract for the **Live Work Studio** draft. It describes
implemented code and remaining release gates, not an assertion of production readiness.

## One-window user flow

- The voice orb remains above a separately scrolling conversation.
- Attachments and URL entry appear in the composer.
- The right panel selects queued/running/completed projects, displays actual
  Work ledger checkpoints, and automatically opens completed artifacts.
- Live and Work share one owner authentication and session scope; no Work login.
- Work executes in an independent worker process. An authenticated queued job
  remains durable when the Live client disconnects or starts another conversation.

## Input support and limits

| Input | Intake | What is indexed | Known limits |
|---|---|---|---|
| TXT / MD | Source index | Unicode text, bounded passages | UTF-8 only; <=8 MB |
| JSON | Source index | Validated JSON text | No remote schema or semantic check |
| CSV | Source index; dataset tool | Header and rows, indexed text; analytics where supported | <=8 MB; analytics <=10k rows |
| XLSX | Source index; dataset tool | Sheet names and cell values | <=8 MB; bounded rows/sheets |
| DOCX | Source index | Body paragraph/table text | <=8 MB; pictures require separate visual understanding |
| PPTX | Source index | Slide text | <=8 MB; visuals not semantically indexed |
| PDF | Source index | Extractable text per page | <=8 MB for Work source path; scanned pages require existing separate visual-PDF flow |
| SQLite (.db/.sqlite/.sqlite3) | Source index | Read-only table schema and bounded samples | <=8 MB; full SQL analytics from DB not yet implemented |
| Public HTTPS URL | Pinned HTTPS fetch | HTML text, plaintext, MD, JSON, CSV, PDF, XLSX | TLS, public IP required, <=8 MB, max 2 redirects |
| PNG / JPG / WEBP | Existing visual tool | Image attached to private Live session | Work delegation from image is not yet integrated |

No source is blindly pasted in full into the Live model. All selected-source
retrieval checks ownership and returns bounded source IDs and offsets. This
improves responsiveness; it does **not** establish full-document analytical
coverage. The Worker handoff currently includes relevant retrieved excerpts,
not a complete coverage report. For definitive claims over huge documents,
the Work engine still needs a resumable full-corpus map/reduce workflow.

## Queuing and recovery

- Job submission uses a durable owner-scoped ledger and idempotency key.
- Worker claims are fenced; SQLite uses an immediate write transaction.
- PostgreSQL uses a short, transaction-scoped advisory lock to serialize
  concurrent job claims before selecting the next eligible task.
- One active project per owner; next queued project starts after terminal state.
- Worker crash recovery, retries and events are inherited from V12.
- Cross-user separation, cancellation, stale leases and simultaneous claims
  must pass SQLite and PostgreSQL CI.

## Preview integrity

- Native artifacts are the source of truth; download requires owner authentication.
- PPTX/DOCX/XLSX previews expose extracted content only, not pixel-perfect layout.
- HTML previews use a sandboxed iframe without script privileges.
- Text and URL data are displayed using textContent, not user-provided HTML injection.
- Visual navigation actions require an existing, completed, owned project.
- Frontend milestones come from persisted step states, not fake percentages.

## Phase gates

| Gate | Validation | Current status |
|---|---|---|
| G1 | Source integrity inventory and Python 3.11/3.12/3.13 offline CI | Automated; re-run for each head |
| G2 | App integration, voice contracts, upload/ownership tests | Automated; re-run for each head |
| G3 | PostgreSQL concurrent queue, fencing, recovery | Automated; re-run for each head |
| G4 | CodeQL, upload safety, SSRF restrictions | Automated; re-run for each head |
| G5 | Live Gemini session with interruption and native tool calls | **NOT IMPLEMENTED** in V13; V12 controller remains |
| G6 | Real Colab GPU mic/voice provider and end-to-end browser | **UNVERIFIED** |
| G7 | High-context >8 MB Work ingestion and full evidence coverage | **NOT IMPLEMENTED** |
| G8 | Pixel-faithful slide/doc rendering and fully interactive dashboards | **NOT IMPLEMENTED** |
| G9 | External source/db analytical correctness vs golden datasets | **UNVERIFIED** |
| G10 | Latency p50/p95/p99, streaming and multi-hour reliability | **UNVERIFIED** |

No release announcement should claim all gates green until actual evidence
has been collected. A CI pass establishes software contract compliance, not
real-time provider availability, semantic artifact quality or visual fidelity.

## Manual demonstration acceptance

1. Connect one authenticated session via HTTPS.
2. Attach a CSV and a public URL; confirm both indexed with source references.
3. Ask for a presentation; confirm a durable queued job receipt.
4. Ask for an unrelated explanation while the worker runs.
5. Submit a second project; confirm it waits while the first is active.
6. Watch human-readable progress updated from saved execution events.
7. Verify the first artifact and open/slide-navigate via preview; download it.
8. Let the second job begin automatically after the first completes.
9. Disconnect, reconnect, and verify persisted jobs and artifacts.
10. Run failure injection (provider timeout, worker termination, bad file,
    unauthorized source, misleading filename, SSRF URL, bad Office archive).
