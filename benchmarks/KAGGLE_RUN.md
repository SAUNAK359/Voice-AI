# Kaggle T4 benchmark and GitHub results upload

**Credentials:** Set Kaggle Secrets `GEMINI_API_KEY` and `GITHUB_TOKEN`. The second is a GitHub fine-grained token scoped to `SAUNAK359/Voice-AI` with **Contents: Read and write**. Neither credential should be placed in source code, notebook outputs, or git remote URLs.

**Runtime:** Kaggle Notebook, Internet enabled, NVIDIA GPU T4/T4x2. T4 runs Whisper ASR; Gemini is a cloud API and does not run on the T4.

`scripts/run_kaggle_benchmarks.py` executes:

| Input / dataset | Workload |
| --- | --- |
| 10 repository prompts (50 requests + 2 warmups by default) | Live Gemini SSE TTFT; goal of 564 ms is not a measurement |
| LibriSpeech `openslr/librispeech_asr`, clean/test | Small streamed subset, Whisper Turbo CUDA, WER/CER, RTF, latency |
| FLEURS `google/fleurs`, en_us/test | Small streamed subset, Whisper Turbo CUDA, WER/CER, RTF, latency |
| Mozilla Common Voice attached through Kaggle Input | Optional, requires separately obtained authorized Mozilla Data Collective files |
| Repository synthetic ASR CSV | Offline scorer smoke test, not a model accuracy claim |
| Repository redacted legacy voice JSONL | One failed historical turn; no success latency claim |
| Repository `examples/` | Offline artifact structural validation |

From the repository root:

```bash
python scripts/run_kaggle_benchmarks.py \
  --output-dir benchmarks/results/kaggle_<unique_run_id> \
  --gemini-model gemini-3.5-flash-lite \
  --repeat 5 --asr-samples 20 --whisper-model turbo
```

Attach `--common-voice-root /kaggle/input` if you have an authorized Common Voice archive with `validated.tsv` (or `test.tsv`) and `clips/`.

The accompanying Kaggle launch cell clones the private repository with an ephemeral Git HTTP authentication header, runs this script, commits **only metrics JSON/JSONL**, and pushes to GitHub. Audio, actual transcripts, model response text, prompts, and secrets are excluded from output.

**Not evaluated:** Live browser first-audible response latency, KittenTTS subjective quality, full production Work Agent task reliability and concurrency. Dataset failures are explicitly reported as unavailable, not as a successful benchmark.
