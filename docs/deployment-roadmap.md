# Hugging Face Spaces deployment roadmap

The current Kaggle notebook is not yet a drop-in Hugging Face Space. The UI is portable, but notebook lifecycle, ephemeral GPU artifacts, in-kernel secrets, background task lifetime and Quick Tunnel assumptions must be replaced.

## Deployment target

- Docker Space: FastAPI application with ASGI server and WebSocket support.
- Platform secrets for Gemini and private UI authentication; no credentials in frontend bundles.
- Pinned Hugging Face compatible CUDA or CPU image depending on chosen hardware and model inference method.
- Startup health / readiness / liveness checks that distinguish listening service from warmed inference.
- PostgreSQL and private object storage for durable jobs and deliverables.
- Per-user identity and protected artifact download URLs; enforce request/body quotas.
- Queue-backed agent execution with retries, timeouts and cancellation acknowledgement.
- Monitoring of GPU memory, TTFT, TTS first PCM, browser playback latency and worker backlog.

The Docker Space, OIDC provider and production job backend are **planned work**, not included functioning in the V9 notebook. Publish them only after test deployment and security validation.
