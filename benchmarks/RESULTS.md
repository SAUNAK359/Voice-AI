# Benchmark results — Rizzler Voice AI

**Evidence:** First live Kaggle model measurements were published on **8 November 2026**. They measure **GPU ASR inference** and **cloud Gemini time-to-first-text**, *not* user-perceived microphone-to-speaker response time.

## 1. Measured CUDA speech recognition — T4, 50 utterances per dataset

| Dataset / test split | Evaluated clips | WER ↓ | CER ↓ | Inference p50 ↓ | Inference p95 ↓ | Real-time factor ↓ | Failed clips |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **LibriSpeech test-clean** | **50** | **3.115%** | **1.233%** | **329.58 ms** | **420.04 ms** | **0.0524** | **0** |
| **Google FLEURS en_us / test** | **50** | **4.833%** | **2.527%** | **360.42 ms** | **424.31 ms** | **0.0385** | **0** |

**Model:** Whisper `turbo` (large-v3-turbo), Faster-Whisper 1.2.1 / CTranslate2 4.8.5, FP16, CUDA on **Tesla T4 GPU 0**. An additional T4 was available but not used. Dataset streaming source revisions, normalization, word/character edit totals, and individual failed-sample counts are recorded in the [raw metrics](results/asr_t4_534e70b217/asr_results.json) and [machine manifest](results/asr_t4_534e70b217/run_manifest.json).

**Methodology limitations:** Each result covers the **first 50 valid streamed utterances** from the named test split, not the full benchmark split and not a randomized sample. Inference latency excludes downloads, dataset decoding, browser voice activity detection, microphone capture, and playback. RTF is cumulative inference seconds divided by audio seconds, not elapsed time for an end-to-end service. WER and CER use corpus-level edit counts after Unicode NFKC, case-folding, punctuation/whitespace normalization. No retained audio or transcripts are published.

## 2. Measured Gemini streaming response latency — live API

| Model | Requests | Median TTFT ↓ | P95 TTFT ↓ | P99 TTFT ↓ | Success |
| --- | ---: | ---: | ---: | ---: | ---: |
| **gemini-3.5-flash-lite** | **50** | **621.79 ms** | **969.71 ms** | **1,191.86 ms** | **50/50** |

**Source:** [live metrics JSON](results/kaggle_20261108_130822_2882d8/gemini_summary.json) and [request-level measurements](results/kaggle_20261108_130822_2882d8/gemini_requests.jsonl), from **10 benchmark prompts × 5 repeats**, plus 2 warmups. The **564 ms median TTFT target was not met**. TTFT is first visible text from a streaming REST request; **it is not first audible audio**, and Gemini inference runs on Google's cloud rather than on Kaggle GPUs.

## 3. Older reported Gemini timing summaries (not V9 measurements)

| Configuration | Requests | Historical median TTFT | Historical P95 TTFT |
| --- | ---: | ---: | ---: |
| Prior Flash-Lite warm streaming | 20 | 1,012.7 ms | 1,136.0 ms |
| Prior persistent API client | 10 | 960.3 ms | 1,076.3 ms |
| Prior fresh API client | 10 | 1,051.0 ms | 1,241.8 ms |

Raw per-request traces were not retained for these older summaries. They should **not** be treated as controlled A/B evidence or directly compared to the newer experiment as an optimization claim.

## 4. Historic failed turn — retained separately

| Older run | Sample | Value | Status |
| --- | ---: | ---: | --- |
| Legacy `small.en` ASR | 1 failed turn | 5,380.5 ms | Failed |
| Legacy full turn | 1 failed turn | 9,248.4 ms | Gemini 503 |

Source: [redacted event](data/legacy_failed_turn.jsonl), 4 November 2026. The original LibriSpeech/FLEURS CUDA-library failures were also resolved in a subsequent run, but **failed attempts remain separate from successfully scored clips**.

## 5. Evaluation coverage / outstanding tests

| Area | Current status |
| --- | --- |
| Whisper Turbo ASR | **Measured on two small labeled English test subsets** |
| Gemini streaming text TTFT | **Measured on 50 requests** |
| Common Voice | **Not evaluated**; authorized dataset was not attached |
| Full LibriSpeech/FLEURS test sets | **Not evaluated**; first 50 valid clips only |
| Browser first-audible end-to-end response | **Not measured** |
| TTS/KittenTTS live voice quality and first PCM | **Not measured** |
| Barge-in under real microphone/echo | **Not measured** |
| Work Agent live accuracy / concurrency | **Not measured** |
| Generated artifact structural tests | **Offline test fixtures only** |

The previously discussed 300 ms first-audio aspiration is **not** an achieved result. A server-reported first audio frame must not be labeled as browser first audible playback.

## 6. Reproduction

```bash
# Historical failure analysis only
python scripts/benchmark.py benchmarks/data/legacy_failed_turn.jsonl

# On a Kaggle T4 with CUDA 12 cuBLAS/cuDNN discoverable and an existing checkout:
python scripts/run_kaggle_benchmarks.py \
  --output-dir benchmarks/results/<unique_run_id> \
  --asr-only --asr-samples 50 --whisper-model turbo

# For a separate Gemini run with GEMINI_API_KEY in Kaggle Secrets:
python scripts/benchmark_gemini.py \
  --model gemini-3.5-flash-lite --repeat 5 --warmup 2
```

Follow [the Kaggle launch instructions](KAGGLE_RUN.md) to set the required CUDA library search paths, use secrets safely, and publish only redacted metrics.

[Dataset inventory](DATASETS.md) · [Benchmark protocol](PROTOCOL.md) · [Repository README](../README.md)
