# Benchmark results — Rizzler Voice AI

**Project:** Rizzler V9 · Real-time Voice AI + Gemini Work Agent  
**Evidence status:** Historical API timing observations and offline software tests are available. **No verified V9 Kaggle GPU end-to-end voice benchmark has been published.**

## 1. Recorded model latency (historical)

TTFT = *time to first visible generated text*. These are older Gemini API timing summaries, **not first audible response** or V9 end-to-end latency. Raw per-request Gemini traces were not retained in this repository.

| Test configuration | Requests | Median TTFT | P95 TTFT | Evidence |
| --- | ---: | ---: | ---: | --- |
| Gemini Flash-Lite — warm streaming requests | 20 | **1,012.7 ms** | **1,136.0 ms** | Historical reported aggregate |
| Gemini — persistent API client | 10 | **960.3 ms** | **1,076.3 ms** | Historical reported aggregate |
| Gemini — fresh API client | 10 | **1,051.0 ms** | **1,241.8 ms** | Historical reported aggregate |

**Interpretation:** First text in these historical samples took roughly one second at the median. These small, non-randomized batches do **not** establish that the persistent client is consistently faster, or that the current V9 system has the same performance.

## 2. Documented failed voice run (not a performance success)

| Test | Samples | Observed measurement | Outcome |
| --- | ---: | --- | --- |
| Legacy speech recognition (older `small.en` setup) | 1 | ASR: **5,380.5 ms** | Failed turn |
| Legacy complete turn | 1 | Duration: **9,248.4 ms** | Failed: Gemini HTTP 503 |

Source: [redacted raw event](data/legacy_failed_turn.jsonl) dated **2026-11-04**. The run was from an older voice/TTS stack, not the V9 Whisper Turbo + KittenTTS configuration. **Exclude this event from successful-turn latency statistics.**

## 3. Current V9 evaluation status

| System component | Target measurement | Verified V9 result | Current status |
| --- | --- | --- | --- |
| End-to-end voice | First **audible** audio, p50/p95/p99 | — | Not yet measured on Kaggle + browser |
| Whisper Turbo ASR | WER, CER, p50/p95 inference time | — | No labeled speech evaluation completed |
| Gemini voice model | TTFT, timeouts, response correctness | — | V9-specific cloud benchmark pending |
| KittenTTS | First PCM latency, real-time factor | — | Live synthesis benchmark pending |
| Interruption / barge-in | Time to stop old playback, stale-audio rate | — | Browser-device trials pending |
| GPU efficiency | Peak VRAM, utilization, throughput | — | Kaggle telemetry benchmark pending |
| Work Agent | Correct task completion, retries, tool-call validity | — | Real Gemini workload benchmark pending |
| Artifact studio | Format validity + factual/visual quality | — | Offline examples exist; complete evaluation pending |
| Concurrent sessions | Success rate and p95 under load | — | Multi-session test pending |

A dash means **not measured**, not zero or failure. The previously discussed **300 ms first-audio objective is aspirational**, not an achieved result.

## 4. Which datasets were actually used?

| Data source / fixture | Used? | What it supports |
| --- | --- | --- |
| Historical Gemini API request batches (20, 10, 10) | **Yes** | Reported TTFT summaries; no attached raw request trace |
| [Legacy failed voice JSONL event](data/legacy_failed_turn.jsonl) | **Yes** | Reproducible analysis of one failed voice turn |
| Synthetic CSV/Excel-style fixture data | **Yes — offline only** | Testing analysis and visualization renderers; not a public accuracy dataset |
| Synthetic report/presentation fixture content | **Yes — offline only** | PDF, DOCX, PPTX, XLSX and PNG output examples; not a live Gemini research benchmark |
| LibriSpeech / Mozilla Common Voice / Google FLEURS | **No** | Candidate datasets for future ASR accuracy testing |
| Labeled research/reasoning golden set | **No** | Not yet established for the Work Agent |

See the [dataset inventory, sample provenance and planned evaluation inputs](DATASETS.md). The synthetic examples are documented in [examples/README.md](../examples/README.md).

## 5. Reproduce results from real event data

```bash
python scripts/benchmark.py benchmarks/data/legacy_failed_turn.jsonl \
  --output /tmp/rizzler_legacy_metrics.json
```

The existing summarizer counts only `outcome=ok` rows toward successful latency aggregates. It must **not** reinterpret a failed turn as a successful performance observation.

For a future V9 Kaggle benchmark, collect consented, redacted `turn_complete` events from actual inference; pair server timestamps with **browser playback timestamps** for user-perceived response time. Record hardware, model IDs, warm/cold policy, number of runs, success/failure counts, p50/p95/p99, and test conditions.

**Measurement boundaries:** VAD = last spoken PCM to endpoint; ASR = endpoint to final transcript; Gemini TTFT = API request to first text; TTS = first phrase to first PCM; first audible audio = final user speech to actual browser playback; barge-in = interruption speech onset to old playback stopped. Server PCM send time is **not** browser audible time.

## 6. Recruiter and engineering interpretation

- **Implemented:** Voice / agent architecture, reproducible offline checks, CI, artifact renderers, event-based benchmark reporting.
- **Evidence available:** Earlier Gemini API latency summaries and a redacted failed voice trace.
- **Not yet demonstrated:** V9 end-to-end speech latency, ASR error rates, production-scale concurrency and live Work Agent quality.

This distinction prevents misleading performance claims while keeping the project's architecture and measurable engineering work easy to assess.
