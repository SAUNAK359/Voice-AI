# V11 — Complete PDF ingestion

## Scope

The previous visual preview only analyzed the first three pages of PDFs with at most 24 pages. The new /api/pdf/documents pipeline replaces that behavior for actual PDF uploads.

**No fixed document page-count or total-file-size product cap.** Every page is extracted, every page is tiled into bounded-size images, every visual tile is sent to read-only vision, and all extracted page text is indexed without truncation. A document is marked complete only when the recorded number of fully indexed pages equals the PDF page count. Questions default to full-document hierarchical analysis, not a fixed first-page sample.

Finite disk space, rate limits, provider cost, invalid documents, memory per operation, and security constraints still apply. These are not bypassed by billing more. Failures create an explicit paused/resumable state rather than falsely reporting full coverage.

## Transport and persistence

1. Authenticated POST /api/pdf/documents creates an owner-private document ID.
2. PUT /api/pdf/documents/{id}/chunks/{seq} uploads sequential 1 MiB pieces with SHA-256 checks. Exact duplicate retries are idempotent; altered/out-of-order uploads fail.
3. Each chunk is AES-GCM encrypted and bound to its authenticated owner, document and sequence. The PDF is reconstructed incrementally, never as a complete in-memory byte array.
4. POST /api/pdf/documents/{id}/complete verifies the PDF structure and scans the complete document with ClamAV in production. Linux reconstruction uses an anonymous temporary file, avoiding a named plaintext copy.
5. The indexer extracts complete page text, hashes search tokens and renders complete page coverage using separate bounded raster tiles. Each tile receives a Gemini vision analysis. Text and visual findings are encrypted and checkpointed.
6. Server-side background processing, leases, heartbeats and a recovery watchdog resume queued or expired work. API progress shows uploaded chunks, indexed/total pages and paused errors. Expired API/model attempts may be resumed without recomputing committed tiles.
7. POST /api/pdf/documents/{id}/research starts a persistent question run. Full mode processes every indexed page and every tile observation, splits long text into bounded units without dropping content, and merges results hierarchically with persisted stage checkpoints. GET /api/pdf/research/{run_id} reports progress and result; POST .../resume handles interrupted runs.
8. Deleting the document erases encrypted chunks, page observations, search tokens, and its associated research results.

## API and frontend

The Visual Context file picker routes PDFs to the full upload protocol and displays indexing status. Reattaching the same file resumes a partial upload from its acknowledged chunk. Once fully indexed, the user selects the document and asks a question; the UI waits for the full-document research result. Images and PDF questions have separate analysis paths so there is no silent mixing/omission.

The old small-visual upload explicitly rejects PDF requests and points clients to the new full-document route.

## Security and operational qualifications

- No media content can authorize private writes or change the system prompt.
- Owner-scoped IDs, encryption, SHA-256 checks, fail-closed malware scanning, bounded model requests and raster tiles are retained.
- ClamAV StreamMaxLength must be set to accept the operational document sizes. If scanning fails or is unavailable, PDF finalization fails.
- Non-Linux deployments need encrypted scratch storage. Kaggle's ephemeral storage needs an external persistence strategy if processing must survive a notebook reset.
- A physically limitless file is impossible. Available storage, API quotas, PDF decoder limits and customer budgets must be monitored; none creates a hidden successful-but-truncated result.

## Verification

The added integration suite tests 126-page ingestion, forced cancellation and checkpoint recovery, encrypted chunk tampering, owner isolation, complete 36-page research, large-page tiling and authenticated 27-page upload/research.

CI with mocked Gemini validates wiring but not live provider quality, difficult scanned documents, adversarial PDFs, hours-long processing, real cost or cross-session Kaggle durability. Production certification still requires live Gemini, real long-document datasets, scanner fault injection, backups/restart drills and accuracy evaluation.

Every page and tile is included in the processing record, but a compressed final answer cannot guarantee that every fact appears in the response. Distinguish complete coverage from factual correctness.
