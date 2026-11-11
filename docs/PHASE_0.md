# Phase 0 — Application-first foundation

## Intent

Turn the Kaggle-centered proof-of-concept into a **native, minimal application** before production-hardening voice or Work Agent features.

## Implemented in this package

- [x] Reusable `create_app()` FastAPI app; `python -m rizzler` entry point
- [x] Core dependency split; live voice and CUDA libraries optional
- [x] Lazy Whisper Turbo, Gemini async streaming, KittenTTS Nano adapters
- [x] Bounded PCM16 audio, resampling, asynchronous phrase-to-TTS worker
- [x] Session-owned HTTP interrupt/reset; WebSocket generation fences
- [x] Replaced notebook-derived frontend in the new app with a small CSP-compatible browser UI
- [x] Unit/integration tests using fake providers (no cloud key or GPU)
- [x] App-specific GitHub Actions, Docker CPU reference, configuration and health endpoint
- [x] Preserved V9 notebook as historical/reference entry point, not the default app server

## Not yet qualified / intentionally excluded

- [ ] **Full Work Agent migration** (existing V9 notebook work jobs and 17 skills are NOT claimed to work in this new app)
- [ ] Real T4 startup and fresh voice turn with external Gemini/KittenTTS on the new service
- [ ] Browser phone first-audible latency, reconnect and barge-in device acceptance
- [ ] Scalable accounts, permanent database, queues, multitenant isolation and production secrets
- [ ] Long-run resource leak tests, 429 budget under load, proper content policy, complete security assessment

## Acceptance matrix

| Gate | Deterministic proof | Live proof still needed |
| --- | --- | --- |
| Import/boot | FastAPI TestClient and `/health` | Production process with actual device providers |
| HTTP turn | Fake ASR/Gemini/TTS and PCM response | Real T4 microphone, Gemini API and Kitten audio |
| WebSocket | Auth, generation and sample-limit tests | Browser HTTPS/WSS and audio playout |
| Cancellation | Session scope and task handling | Native CUDA cancellation under concurrent speech |
| Security | Deny missing key, validate session and body limits | Full external audit / SSO |
| Benchmark | Preserved baseline and methodology | Comparable real app E2E telemetry |

**Do not mark Phase 0 complete for production until a clean live smoke test on target hardware passes.**
