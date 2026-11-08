# Dataset and evaluation input inventory

Rizzler is a **voice AI application**, not a model-training release. The data below were used for *evaluation and implementation testing*, not to train Whisper, Gemini, or KittenTTS. This inventory distinguishes historical aggregates, synthetic fixtures, and measured live inference.

## Used in the repository or preceding development

| Input | Origin and size | Used for | Important limitation |
| --- | --- | --- | --- |
| Historical Gemini streaming requests | Previously reported aggregate, **20 warm calls** | Gemini first-text latency | Raw per-request samples are not published |
| Historical persistent Gemini client | Previously reported aggregate, **10 calls** | API client TTFT comparison | Different small batch; not a controlled A/B study |
| Historical fresh Gemini client | Previously reported aggregate, **10 calls** | Comparison to persistent client | Model/network variance not controlled |
| `benchmarks/data/legacy_failed_turn.jsonl` | **1** redacted failed event, 2026-11-04 | Failure handling and metrics summarizer | Older ASR/TTS stack, Gemini 503; not a V9 success |
| Synthetic tabular fixture (CSV/Excel-style data) | Generated locally for **offline tests** | Profiling, charts and analytical output formatting | Not a real-world accuracy or performance benchmark |
| Synthetic report and presentation content | Generated locally for **offline render tests** | PDF, DOCX, PPTX, XLSX and PNG examples | Not a real Gemini research task or factuality dataset |
| Deterministic unit-test inputs | Local test cases under `tests/` | State machine, schemas, authentication, metrics and file structures | Software contract tests, not live inference benchmarks |

The packaged examples in [`examples/`](../examples/README.md) demonstrate **artifact format and layout**. No private speech recordings, API keys, or transcripts should be committed for public benchmarking.

## New measured public audio evaluations — 8 November 2026

| Dataset / split | Evaluated audio | Model and device | Provenance |
| --- | --- | --- | --- |
| **LibriSpeech test-clean** (`openslr/librispeech_asr`, `clean`/`test`) | **50 first valid utterances** | Whisper Turbo FP16, Tesla T4 CUDA:0 | [ASR metrics](results/asr_t4_534e70b217/asr_results.json) |
| **Google FLEURS English (US)** (`google/fleurs`, `en_us`/`test`) | **50 first valid utterances** | Whisper Turbo FP16, Tesla T4 CUDA:0 | [ASR metrics](results/asr_t4_534e70b217/asr_results.json) |
| **Gemini streaming prompts** (10 fixed repository prompts × 5) | **50 live API calls + 2 warmups** | Gemini cloud API, separate from Kaggle GPUs | [Gemini summary](results/kaggle_20261108_130822_2882d8/gemini_summary.json) |

These are evaluation inputs, **not model-training datasets**. The ASR sample selection was a small deterministic subset and not a full test-set comparison. Dataset source revisions and error totals are retained with the metrics.

## Not used yet — planned public datasets

| Proposed dataset | Intended benchmark | Current status |
| --- | --- | --- |
| Mozilla Common Voice | Accent and microphone robustness | **Not evaluated** |
| Other FLEURS language splits | Multilingual speech recognition beyond English (US) | **Not evaluated** |
| Controlled noise-augmented speech set | ASR robustness under SNR shifts | **Not created/evaluated** |
| Human-reviewed voice + reasoning tasks | Response correctness, hallucination and instruction-following | **No gold labels yet** |
| Golden Work Agent task set | Tool success, factuality, numeric correctness and artifact coverage | **No curated benchmark yet** |
| Device-recorded interruption trials | Barge-in and playback cancellation | **No complete device-run trace yet** |

Do not describe remaining planned datasets as used or evaluated. The two English audio subsets above **have** now been evaluated; their full test splits have not.

## Evidence policy

1. Publish the **sample count**, model and version, hardware, timing boundary, status and raw or aggregated provenance.
2. Keep **historical aggregates**, **synthetic offline tests**, and **V9 live measurements** in separate tables.
3. Include both successes and errors; compute successful-turn latency only from successful turns.
4. For WER/CER, use a labeled reference transcript set and publish normalization/scoring rules.
5. For first-audible latency, instrument the **browser speaker playback**, not only server PCM generation.
6. Redact personally identifying speech, transcripts, files, URLs containing access tokens and all API secrets.

[Results and definitions](RESULTS.md) · [Project overview](../README.md)
