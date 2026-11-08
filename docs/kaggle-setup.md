# Kaggle NVIDIA GPU quickstart

## Prerequisites

- Kaggle notebook with **Internet enabled** and NVIDIA accelerator selected.
- Attached Kaggle Secrets: `GEMINI_API_KEY`, `RIZZLER_ACCESS_KEY` (16+ random characters).
- A Gemini API key authorized for the specific configured model IDs. Model availability and service quotas change independently of notebook version.

## Runbook

1. Import the standalone V9 notebook from `notebooks/` and use **Run All** in exact cell order.
2. The first cell verifies `torch.cuda.is_available()`, `torch.version.hip is None`, and `nvidia-smi` before installing anything.
3. The dependency cell preserves Kaggle's CUDA-compatible PyTorch and attempts to locate cuBLAS/cuDNN for CTranslate2.
4. Secrets are read through `UserSecretsClient`; no key should be printed or present in code cells.
5. Whisper and KittenTTS must synthesize/transcribe actual warmup samples; the Gemini smoke test must return visible text.
6. The **complete** FastAPI server cell must run before `9A` Work Agent route registration. A preflight cell checks `/`, `/health`, `/ws`, `/api/auth`, `/api/turn`, `/api/interrupt`, `/api/reset`.
7. Launch the server; check `/health` and authenticate using the *UI access key*, not the Gemini API key.
8. Start a session and try a 3-second question. If WebSocket fails, run the optional Gradio HTTPS fallback cell and test record → stop → transcript → spoken answer.

## Troubleshooting

| Symptom | First action |
| --- | --- |
| `ModuleNotFoundError: fastrtc` | Use this notebook version; it has no FastRTC requirement. |
| `NameError: RIZZLER_V5_APP` | Re-run the **complete** voice-server cell, not merely its imports; then run verification cell before 9A. |
| `401 Unauthorized` | Supply `RIZZLER_ACCESS_KEY` in the UI; don't confuse it with `GEMINI_API_KEY`. |
| Gemini `404 model not found` | Choose an actual Gemini model visible to your API project; do not blindly downgrade/rename models. |
| Gemini `429` / `503` | Inspect quota and server conditions; bounded retries and explicit fallback should not hide repeated failure. |
| Microphone records but no transcript | Try HTTPS fallback; verify that audio uploads and ASR callbacks are invoked. |
| WebSocket cannot connect | Check tunnel/proxy WebSocket support; use HTTPS fallback rather than claiming live interruption works. |
| KittenTTS silent / robotic | Run sample synthesis, check playback, sample rate and output buffering; rate adjustment alone cannot ensure expressiveness. |

## Reproducibility

Save a redacted hardware/versions report (Python, torch, CUDA, CTranslate2, model IDs) before running benchmarks. Never publish keys, private transcripts or raw work datasets. Clear notebook outputs before pushing source.
