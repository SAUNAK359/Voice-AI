# Benchmark readiness checklist

| Evaluation area | Runner or contract | Ready to execute? | Evidence status |
| --- | --- | --- | --- |
| Gemini TTFT (streaming REST) | `scripts/benchmark_gemini.py` | Yes, with Gemini API key + Internet | Live V9 run not executed |
| 564 ms median TTFT goal | `benchmarks/TARGETS.json` | Target evaluation in Gemini runner | Target only; not measured |
| Whisper ASR WER/CER | `scripts/score_asr.py` | Yes, when labeled reference/hypothesis CSV is supplied | No public ASR dataset evaluated |
| Voice-stage latency | `scripts/benchmark.py` | Accepts actual JSONL events | No V9 browser E2E trace |
| Artifact structure | `scripts/benchmark_artifacts.py` | Yes, on existing examples or live job outputs | Does not score visual/factual quality |
| CUDA / GPU throughput | Kaggle live notebook runtime | Requires actual GPU measurement | Not yet benchmarked |
| Barge-in / browser audio | Browser playback timing collection | Requires device-level instrumentation | Not yet benchmarked |
| Multi-user workload | Authenticated load-test environment | Requires live deployment and user-session isolation checks | Not yet benchmarked |

**Publishable headline today:** The Rizzler project includes a reproducible benchmark harness, tested offline scoring tools and historical latency evidence. It has **not** demonstrated 564 ms Gemini TTFT or sub-second end-to-end voice response.
