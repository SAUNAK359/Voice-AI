# Rizzler — project brief for recruiters and engineering reviewers

## One-sentence description

**Rizzler is a GPU-backed, real-time voice assistant that combines streamed speech recognition and synthesis with a Gemini-powered conversational model and a separately governed asynchronous research and artifact-generation agent.**

## What it demonstrates

| Area | Engineering evidence |
|---|---|
| AI / speech | Whisper large-v3-turbo, NVIDIA CUDA with runtime fallback, ONNX KittenTTS, phrase-level speech synthesis |
| Real-time systems | Browser AudioWorklet, PCM16 WebSocket streaming, VAD, barge-in cancellation, response generation IDs, HTTPS fallback |
| LLM orchestration | Streaming Gemini client, bounded retries, conversation state, task routing, JSON-schema handoffs and tool policies |
| Backend | FastAPI, authenticated endpoints, SQLite/WAL job ledger, asynchronous workers, status events |
| Applied data engineering | CSV/Excel profiling, correlations, aggregations, dataset-scoped tools, provenance requirements |
| Artifact engineering | Editable PPTX/DOCX/XLSX, PDF, HTML, charts, structured exports and integrity manifest |
| Quality and delivery | CI workflow, CodeQL config, Python-version matrix, deterministic contract tests, secret scanner, benchmark protocol |

## Recruiter-facing description (accurate)

Designed and implemented **Rizzler**, a Gemini-powered real-time voice AI and asynchronous task-execution prototype. Built a browser-to-FastAPI speech pipeline with Whisper Turbo CUDA recognition, streamed model responses, KittenTTS male speech, interruption handling and HTTPS fallback. Integrated a separate schema-governed Work Agent for research, structured analysis, document generation and persistent job-status reporting. Packaged a Kaggle-ready notebook with GitHub Actions, security checks, benchmark provenance and testable modules.

## Benchmark evidence and dataset disclosure

| Historical measurement | Sample size | Median | P95 | Scope |
| --- | ---: | ---: | ---: | --- |
| Gemini Flash-Lite TTFT | 20 | 1,012.7 ms | 1,136.0 ms | API text latency only |
| Gemini persistent-client TTFT | 10 | 960.3 ms | 1,076.3 ms | API text latency only |
| Gemini fresh-client TTFT | 10 | 1,051.0 ms | 1,241.8 ms | API text latency only |

**Data used:** Historical model request summaries, one failed legacy voice JSONL trace, and synthetic tabular/content fixtures for offline tests. **Data not used yet:** LibriSpeech, Common Voice, FLEURS or a labeled golden Work Agent benchmark. There is **no verified V9 first-audible p50/p95 measurement**; 300 ms remains a stretch goal.

[Benchmark tables](../benchmarks/RESULTS.md) · [Dataset inventory](../benchmarks/DATASETS.md)

## Engineering reviewer notes

- **What runs:** canonical Kaggle notebook with embedded browser UI and FastAPI voice/work routes. Separate modules in `src/rizzler/` validate contracts and patterns; they are not yet used as a fully extracted service runtime.
- **What was tested:** offline Python/JS syntax, contract/state/secret tests, artifact structural tests and mocked work jobs.
- **What is not verified:** live V9 Kaggle/phone E2E p50/p95 voice latency, interruption under echo/noise, multi-user concurrency and full-scale enterprise security.
- **Metrics:** historical Gemini-only TTFT median ~1.0 second; the 300 ms first-audio figure is a target, not a measured accomplishment.

This positioning foregrounds real architecture and working artifacts without inventing production adoption, reliability guarantees or benchmark wins.

[Voice pipeline](voice-pipeline.md) · [Work Agent architecture](work-agent-architecture.md) · [Benchmark provenance](../benchmarks/RESULTS.md)
