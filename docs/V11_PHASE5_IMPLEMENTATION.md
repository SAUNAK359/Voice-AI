# Rizzler V11 Phase 5 — Multimodal Intelligence

## Delivered

The native app accepts explicitly shared PNG, JPEG, WebP and PDF attachments, plus one-frame screen capture initiated by a browser user gesture. Visual questions work through chat and finalized voice. A visual report is submitted to the durable Work Agent only after an additional explicit user confirmation. No continuous video, background screen surveillance or autonomous clicking has been implemented.

Backend: authenticated uploads -> optional production malware scanning -> validated media normalization -> AES-GCM encrypted owner-scoped SQLite storage -> read-only VisualService -> bounded image and PDF page evidence -> Gemini multimodal provider without model tools -> visual answer and explicit unverified-source label. Report handoff uses a 15-minute session-bound token and WorkStore idempotency; persisted Work tasks survive voice interruption or visual deletion.

Every attachment is at most 8 MB. Each owner has at most six active files and 25 MB, with 24-hour expiry. Images are normalized to JPEG, capped at 20 million input pixels and max 2048-by-2048 output, stripping EXIF. PDFs are limited to 24 pages; analysis renders up to three pages per file and reports uninspected pages. One question can reference at most four distinct media IDs and eight images. Requests cannot silently grant tools through image or PDF content.

Routes: POST/GET /api/visual/attachments, DELETE /api/visual/attachments/{id}, POST /api/visual/ask, POST /api/visual/report. The existing /api/runtime and /api/voice/tools report multimodal state. All private routes reuse the normal authenticated owner context.

## Deployment

Set RIZZLER_VISUAL_ENABLED=1, an independent random 32+-byte RIZZLER_VISUAL_KEY and an absolute non-symlinked RIZZLER_VISUAL_ROOT (defaults beneath the Work root). Production reuses its mandatory malware scanner and fails closed. The canonical Kaggle notebook reads the optional RIZZLER_VISUAL_KEY secret, enables visual mode when provided and checks its startup wiring. Kaggle storage is ephemeral.

## Failure policy

Reject untrusted content with malformed MIME, extension mismatch, corrupt or encrypted PDF, decompression bombs, excessive pages, modified ciphertext, duplicate IDs, expired objects, cross-owner access, provider timeout and failed malware scans. Never claim visual findings are independently verified. PDF contents and screenshot text are treated as data, not instructions. Speech visual intents run only after final ASR. Work reports require a separate, explicit user action and an owner-bound analysis confirmation.

## Testing

The Python 3.11–3.13 app matrix includes tests/test_v11_phase5.py alongside all previous tests. Tests exercise real image decoding, PDF rendering, encrypted storage, owner isolation, mocked provider success/failure, voice handoff, idempotent report submission, actual WorkStore execution and artifact QA. Node syntax checks, CodeQL and PostgreSQL compatibility remain in CI.

## Unverified production gates

This does not provide calibrated OCR, claim-level fact-checking, real-time video, autonomous GUI navigation, PDF malware disarm/reconstruction, cross-worker media replication or mobile audio/video streaming. Real Gemini, live Android Chrome/iOS Safari capture permission, HTTPS operation, adversarial screenshots, handwritten/occluded diagrams, RTL/Unicode pages, visual accuracy, source citations, memory usage, ClamAV outages, backups and latency must be measured on a deployed runtime before production qualification.
