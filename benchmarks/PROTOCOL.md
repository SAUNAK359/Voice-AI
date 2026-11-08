# Reproducible Rizzler benchmark protocol

## Target versus evidence

**564 ms is an engineering goal for median Gemini time to first visible text (TTFT), not an observed result.** The historical values remain 1,012.7 ms (20 calls), 960.3 ms (10 calls), and 1,051.0 ms (10 calls). Never replace these with the target or report a CI/mock result as live latency.

## 1. Live Gemini TTFT — ready to run with Kaggle Secrets

The runner uses the Gemini `streamGenerateContent?alt=sse` endpoint and sends `x-goog-api-key` in the request header. It performs actual billable/quota-consuming requests only without `--dry-run`. Requires Internet and access to the chosen model.

```bash
# Offline validation, no Gemini key needed and no latency result generated
python scripts/benchmark_gemini.py --dry-run

# Live measurement, with GEMINI_API_KEY in Kaggle Secrets or environment
python scripts/benchmark_gemini.py \
  --model gemini-3.5-flash-lite \
  --prompts benchmarks/fixtures/gemini_prompts.jsonl \
  --repeat 5 --warmup 2 --cooldown-ms 1500 \
  --output /kaggle/working/rizzler_ttft.jsonl \
  --summary /kaggle/working/rizzler_ttft_summary.json
```

The included 10 prompts multiplied by five repeats give **50 measured requests**, plus two uncounted warmups. Use a model that is accessible on your key. Avoid attempting high request rates on an account with low quota; the runner intentionally has no automatic retry. Failures remain in JSONL and are excluded from successful TTFT aggregates, but included in success-rate denominator.

**Definitions:** TTFT starts immediately before HTTP streaming request submission and ends at first *non-thought visible text* SSE fragment. It includes networking/provider overhead. The first SSE event can be metadata or thought, and **is not** TTFT. Metrics include total request time, error status, first SSE event, output character count, and optional usage token count. No actual prompt text, generated response text, or API key is recorded.

**Protocol metadata to attach:** UTC run time, Kaggle machine/GPU, CPU/RAM, operating system, model ID, client location, model/request settings, prompt set version, cooldown, warmups, measured samples, errors, and run identifier. Existing runner stores model/settings/request identifiers; supplement with hardware/runtime evidence. Report p50, p95, p99, min/max and error rate. At least 30 successful responses are needed before the report evaluates the **564 ms p50 goal**. Values below that threshold are reported but labeled insufficient evidence for target assessment.

## 2. Speech recognition accuracy — ready with labeled transcriptions

```bash
# Smoke test with SYNTHETIC CSV data; NOT a real ASR benchmark
python scripts/score_asr.py \
  --input benchmarks/fixtures/asr_synthetic_smoke.csv \
  --dataset-id synthetic_smoke_only \
  --output /tmp/asr_smoke.json

# Replace with actual model predictions and human/reference transcriptions
python scripts/score_asr.py --input /path/to/real_asr_predictions.csv \
  --dataset-id librispeech_clean_explicit_version --output /tmp/real_asr.json
```

Input CSV must have `reference` and `hypothesis` columns. The scorer uses corpus-level Levenshtein edit distance to calculate WER and CER after Unicode normalization, case folding, punctuation removal, and whitespace normalization. WER and CER are accuracy, **not latency**. The runner cannot verify that the CSV truly came from a named public dataset; include collection, version, license, split, model, device and sample size when publishing real results.

## 3. Existing voice event analysis

```bash
python scripts/benchmark.py benchmarks/data/legacy_failed_turn.jsonl --output /tmp/legacy_voice_metrics.json
```

This intentionally yields **zero successful turns** and no latency percentile claims from the legacy failed event. For a future full V9 run, record real server endpoint/ASR/LLM/TTS spans plus browser clock-synchronized first-audible and interruption timestamps; the original notebook still needs an instrumented live run to obtain those data.

## 4. Artifact structural checks — offline

```bash
python scripts/benchmark_artifacts.py examples/ --output /tmp/rizzler_artifact_checks.json
```

The validator checks format signatures, JSON parsing, OOXML ZIP structure/CRC, SVG XML, column consistency, and nonblank UTF-8. This is **structural quality only**. It does not establish factual accuracy, brand/design aesthetics, slide overflow, Excel recalculation, accessible PDF rendering, or good research citations.

## 5. Evidence publication gate

- Never edit historical TTFT tables to represent targets or hypothetical improvements.
- Publish real benchmark logs only after redacting any keys, credentials, names, voice/transcripts and unique private information.
- Separate `historical aggregate`, `offline smoke fixture`, `measured live inference`, and `not measured`.
- Clearly distinguish first visible text TTFT from first spoken output and browser first audible sound.
- Test success and failure counts; don't discard failed requests when reporting overall reliability.
- CI runs only offline tests. Running GitHub Actions does **not** produce live Kaggle or Gemini latency measurements.

Official Gemini REST reference: https://ai.google.dev/api/generate-content
