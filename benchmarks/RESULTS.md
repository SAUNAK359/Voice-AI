# Rizzler performance evidence

**Benchmark disclosure: no successful V9 Kaggle GPU end-to-end browser benchmark is attached.** The 300 ms first-audio goal is aspirational; no p50/p95 end-to-end claim should be made for V9 without a representative raw event trace and browser playback timestamps.

## Historical measured/reported results

| Run description | Samples | Metric | Value | Provenance and caveat |
| --- | ---: | --- | ---: | --- |
| Prior Gemini Flash-Lite streaming benchmark | 20 warm requests | Gemini first visible text (median) | 1012.7 ms | Earlier reported summary, raw request-level trace not supplied |
| Same 20-request run | 20 | TTFT p95 | 1136.0 ms | Same model family, not V9 browser E2E |
| Prior Gemini persistent-client benchmark | 10 | TTFT median | 960.3 ms | Earlier reported summary; non-randomized small-N comparison |
| Same persistent-client run | 10 | TTFT p95 | 1076.3 ms | No causal claim about connection pooling |
| Prior fresh-client comparison | 10 | TTFT median | 1051.0 ms | Earlier reported summary, alternate arm |
| Same fresh-client comparison | 10 | TTFT p95 | 1241.8 ms | Alternate arm; can be affected by service variance |
| Legacy recorded voice test on 2026-11-04 | 1 **failed** turn | ASR | 5380.5 ms | Legacy `small.en`/Qwen TTS environment, not V9 |
| Same failed turn | 1 **failed** turn | Failed turn duration | 9248.4 ms | Gemini 503 outage; **exclude from successful performance** |

The legacy trace was redacted into [`data/legacy_failed_turn.jsonl`](data/legacy_failed_turn.jsonl), retaining the failed outcome. Do not fold its error into successful latency statistics or compare its ASR to newer Whisper Turbo without matching hardware/model configurations.

## Reproduce the report from a real session

1. Run V9 on Kaggle and record actual `turn_complete` events to a local JSONL file without transcripts or API keys.
2. Add frontend playback timestamps if claiming user-perceived first audio latency.
3. Generate a report: `python scripts/benchmark.py /path/to/redacted_events.jsonl --output metrics.json`.
4. Report device, GPU memory, model versions, API model IDs, runtime versions, warmup policy, sample size, success/error count, concurrency and confidence intervals.
5. Benchmark at least 50 realistic turns across brief/general/reasoning/math/research, separately scoring speech-recognition errors, user barge-in responsiveness, P50/P95, TTS synthesis latency and browser playback delay.

## Measurement definitions

- **VAD endpoint**: last speech PCM sample to endpoint confirmation.
- **ASR latency**: endpoint confirmed to final transcript ready.
- **Gemini TTFT**: model request started to first visible text delta; includes provider/network overhead.
- **TTS first PCM**: first spoken phrase submitted to first synthesized PCM frame.
- **Server first audio**: confirmed endpoint to first outgoing audio frame; NOT identical to browser playback.
- **End-to-end first audible sound**: last user speech to first frame actually played in browser.
- **Barge-in latency**: user speech onset to old audio queue stopped, measured client side.

**Do not treat generated UI animation or simulated mock tests as performance evidence.**
