# Rizzler benchmarks — quick guide

**What is available now?** Historical Gemini time-to-first-text summaries; one documented failed legacy voice turn; and deterministic offline software/artifact tests. **Live V9 end-to-end microphone-to-speaker performance has not yet been recorded.**

| Document | Purpose | Best for |
| --- | --- | --- |
| [RESULTS.md](RESULTS.md) | Compact measurement tables, success/failure status, and reproduction commands | Recruiters and engineers |
| [DATASETS.md](DATASETS.md) | What data were actually used versus proposed, with provenance | ML and research reviewers |
| [data/legacy_failed_turn.jsonl](data/legacy_failed_turn.jsonl) | Redacted raw event for one historical failure | Backend and observability reviewers |
| [../scripts/benchmark.py](../scripts/benchmark.py) | Repeatable JSONL event summarization | Engineers |

**Definitions:** TTFT = time to first generated text; p50 = median; p95 = 95th percentile; WER = word error rate; CER = character error rate. These measure different aspects of system quality.

**Read results carefully:** A mocked unit-test pass is not a GPU benchmark, an HTTP error is not a successful turn, and text TTFT is not audio playback latency.
