# Rizzler V14 — Native Live / 200 MB / Artifact Studio Release Gates

This document is an implementation and qualification ledger. Automated checks
are not evidence that a live provider, mobile microphone, large database, or
human-oriented artifact quality performs correctly in production.

## Phase 1 — Native Gemini Live

- [x] Authenticated browser-to-server Live WebSocket; API key remains server-side.
- [x] Real PCM input at 16 kHz and output at 24 kHz through persistent Gemini Live.
- [x] Model-directed Work queue, status, source search and visual navigation calls.
- [x] Browser interruption stops audio playback; provider interruption events handled.
- [x] Native output and input text transcriptions in the conversation pane.
- [x] Native Live session used preferentially over legacy ASR/TTS when enabled.
- [ ] Provider-verified audio transport, reconnection tokens, microphone persistence.
- [ ] Adaptive medium/high reasoning levels validated for the selected Live model.
- [ ] Long-session natural interruption and device-compatibility qualification.

Production configuration: `GEMINI_API_KEY`, `RIZZLER_LIVE_MODEL`, and
`RIZZLER_NATIVE_LIVE=1`. The model must support native audio and tool calling.
The server MUST NOT send `GEMINI_API_KEY` to the browser. If the provider is
unavailable, report the failure rather than claim a successful Live turn.

## Phase 2 — Large sources and context

- [x] 200,000,000-byte per-file cap for disk-backed streamed uploads.
- [x] One-MB chunk SHA-256 verification, replay protection and owner-scoped offsets.
- [x] Durable metadata and verified final-file digest; production full-file malware scan.
- [x] Streaming text, CSV, Office, PDF and read-only SQLite extraction.
- [x] Full extracted-text indexing with source offsets and searchable passages.
- [x] FTS5 retrieval avoids a linear corpus read on each question.
- [x] S3 object storage allows up to 200 MB per object.
- [ ] True end-to-end complete-source Work analysis over every indexed passage,
      with durable coverage attestations and hierarchical model reduction.
- [ ] Cross-machine source-index hydration and replicated original source bytes.
- [ ] Semantic embeddings, multimodal diagrams, scanned PDFs, image-only documents.
- [ ] Full-fidelity SQL analytics for uploaded SQLite databases.
- [ ] 200 MB external URL fetch remains bounded separately.

An index covering all extracted text is NOT proof the agent reasoned over every
page or row. Source retrieval returns relevant excerpts with explicit
`retrieved_excerpts_only` coverage. A full-corpus report must not claim
comprehensive coverage until the Worker has auditable per-section evidence.

## Phase 3 — Pixel-faithful previews

- [x] Authenticated page-info and page-image endpoints for PDF, Word,
      PowerPoint and Excel, using LibreOffice where conversion is necessary.
- [x] Browser shows actual rendered page bitmaps with page/slide navigation.
- [x] Safe structured-text fallback where the renderer is missing.
- [x] Original editable artifacts remain downloadable.
- [ ] Pixel-identical parity with MS Office (depends on renderer and fonts).
- [ ] Fully interactive dashboards with filtering, links, drilldowns and
      keyboard-driven graphical editing across all artifact kinds.

## Phase 4 — Artifact quality

- [x] Original structural and numeric validation remains in effect.
- [x] Strict page rendering QA checks physical bounds and text visibility.
- [x] Independent model visual review examines actual rendered pages in
      bounded batches, fails closed for serious visual issues.
- [x] Production Docker image opts into `RIZZLER_ARTIFACT_QA=agentic`.
- [ ] Automatic model-directed artifact repair with versioned, independently
      revalidated results.
- [ ] Independent factual source verification and calibrated aesthetic benchmarking.
- [ ] Visual QA full coverage beyond the current 120-page model-review limit.

## Phases 5–6 — Device and release qualification

These cannot be certified from CI alone. Need real Gemini credentials and a
mobile/desktop browser: microphone/STT/voice interruptions, provider limitations,
queue persistence, 200 MB upload verification, genuine source-based artifacts,
pixel preview fidelity, cost and latency p50/p95/p99, crash recovery and security
failure injection.

### Continuous-integration commands

```sh
python -m pytest -q tests/test_v13_studio.py tests/test_v14_large_sources.py tests/test_v14_rendering.py
python -m compileall -q src/rizzler
node --check src/rizzler/web/native-live.js
node --check src/rizzler/web/studio.js
python scripts/verify_release.py
```

## Release decision

V14 is a draft until provider/device validation, true complete-corpus Work
coverage, artifact repair, factual QA, and production deployment checks pass.
Do not describe these unchecked gates as complete in launch announcements.
