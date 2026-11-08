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

## Verified benchmark evidence (Kaggle T4, November 2026)

| Measured workload | Samples | Primary metric | Secondary metric |
| --- | ---: | --- | --- |
| Whisper Turbo — LibriSpeech test-clean | **50** | **3.115% WER** | **329.58 ms median / 420.04 ms P95 inference** |
| Whisper Turbo — FLEURS `en_us`/test | **50** | **4.833% WER** | **360.42 ms median / 424.31 ms P95 inference** |
| Gemini streaming REST API | **50** | **621.79 ms median TTFT** | **969.71 ms P95, 50/50 successful** |

**Benchmark scope:** First 50 valid samples per audio dataset, FP16 T4 inference on GPU 0; *not* full-corpus WER, microphone-to-speaker latency or a controlled model comparison. Gemini runs in the cloud. The **564 ms TTFT goal was not met**. Earlier Gemini historical runs and the failed voice event remain documented separately.

[Verified raw ASR metrics](../benchmarks/results/asr_t4_534e70b217/asr_results.json) · [Gemini run summary](../benchmarks/results/kaggle_20261108_130822_2882d8/gemini_summary.json) · [Benchmark report](../benchmarks/RESULTS.md) · [Dataset inventory](../benchmarks/DATASETS.md)

## Engineering reviewer notes

- **What runs:** canonical Kaggle notebook with embedded browser UI and FastAPI voice/work routes. Separate modules in `src/rizzler/` validate contracts and patterns; they are not yet used as a fully extracted service runtime.
- **What was tested:** offline Python/JS syntax, contract/state/secret tests, artifact structural tests and mocked work jobs.
- **What is not verified:** live V9 Kaggle/phone E2E p50/p95 **first-audible** voice latency, interruption under echo/noise, multi-user concurrency and full-scale enterprise security.
- **Metrics:** Verified ASR subset WER **3.115% LibriSpeech / 4.833% FLEURS** and Gemini median TTFT **621.79 ms**; **300 ms first-audio remains a goal**, not a measured accomplishment.

This positioning foregrounds real architecture and working artifacts without inventing production adoption, reliability guarantees or benchmark wins.

[Voice pipeline](voice-pipeline.md) · [Work Agent architecture](work-agent-architecture.md) · [Benchmark provenance](../benchmarks/RESULTS.md)
