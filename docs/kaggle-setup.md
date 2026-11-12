# Kaggle NVIDIA GPU — V11 native launch

The canonical V11 integration is [Rizzler_V11_Unified_Native_Kaggle.ipynb](../notebooks/Rizzler_V11_Unified_Native_Kaggle.ipynb). Use the native package source and launch `python -m rizzler` plus the separate `rizzler.work_worker` process; **do not use the historical V9 notebook** to validate V11 voice or memory behavior.

## Required setup

1. Kaggle notebook: enable Internet and an NVIDIA GPU accelerator.
2. Kaggle Secrets: `GEMINI_API_KEY` (configured/current provider) and `RIZZLER_ACCESS_KEY` (minimum 16 random characters).
3. Run the V11 notebook cells in order. It checks package import, GPU, private Work root, runtime startup and `/ready`; inspect the exact Git SHA it prints.
4. Optional encrypted memory: set `RIZZLER_MEMORY_ENABLED=1` and a separate `RIZZLER_MEMORY_KEY` (at least 32 bytes). Memory is disabled otherwise and all Kaggle data is ephemeral.
5. For phone microphones, expose the running app using a **trusted HTTPS/WSS reverse proxy or tunnel** and private authentication. The notebook does not automatically open a public tunnel.
6. Run real authenticated voice, Work Agent, search and restart tests; record redacted GPU/model versions, outcomes, first audible p95 and failed turns. A ready server is not an acoustic benchmark.

## Known limitations

Kaggle notebook storage and compute can stop or disappear; scheduled Work cannot continue while the kernel is suspended. Its private Work directory is not off-host durable storage. Do not claim permanent backups, multi-tenant identity, physically measured latency, live Gemini search success, or long-term memory durability from offline CI.

For an actual persistent host, follow [V10 production deployment](PHASE_5.md) and the [V11 Phase 4 qualification contract](V11_PHASE4_IMPLEMENTATION.md). The previous V9 notebook remains in `notebooks/` for independent historical reproduction only.

## Troubleshooting

- NVIDIA missing: enable a compatible accelerator before running.
- Gemini 404 or quota error: confirm the exact configured model and API project; do not invent a fallback.
- TTS/Whisper import error: check the Python, CUDA, CTranslate2 and package versions in the active Kaggle image.
- Microphone unavailable on phone: ensure trusted HTTPS, browser permission and WebSocket forwarding.
- Missing memory key: memory is opt-in; disable it or supply an independent encryption secret.
- Work persistence: configure real persistent Postgres/S3 and independent backup/restore outside Kaggle for production.
