# Architecture and engineering decisions

## Truthful classification

The canonical runnable demo is a sequential Kaggle notebook. It starts a FastAPI app in the Kaggle process and uses Cloudflare Quick Tunnel as an optional development endpoint. This repository also contains portable, tested core contracts. The runtime is **not yet** decomposed into independently deployed microservices, a distributed worker fleet or a dedicated multi-tenant system.

## Real-time voice control plane

**Client**: browser microphone → AudioWorklet PCM16 capture → voice activity detection → WSS. The UI can use record-and-stop HTTPS when full duplex is blocked. **Backend**: native FastAPI WebSocket receives PCM, pre-roll audio, speech_start/speech_end markers and cancellation messages. A generation number fences late audio/text frames from interrupted requests. **Inference**: Whisper Turbo CUDA for final ASR; Gemini streams visible text (not private thoughts); text is chunked for KittenTTS; browser playback is streamed and can be discarded on a new generation. **Telemetry**: typed stage boundaries are needed to separate mic capture, VAD endpoint, ASR, Gemini TTFT, first PCM and actual browser playback. Partial transcripts are provisional.

### Invariants strengthened in this repository

`src/rizzler/state.py` implements a validated session state machine and a generation fence. `src/rizzler/metrics.py` only computes latency statistics from successful observed records; missing samples stay missing. `src/rizzler/security.py` gives constant-time access-key comparison, strict session identifiers, upload filename validation and secret redaction. These modules are testable independently; **the notebook's existing runtime does not yet import them**.

### Current bottlenecks and limitations

- Historical Gemini TTFT median around 1 second before persistent-client tuning. These runs precede V9 and are not comparable to browser-first-audio latency.
- KittenTTS speed control is not equivalent to genuine emotive prosody; expressive model A/B testing is necessary.
- Client-side VAD and local browser echo cancellation need device tests, and audio output may leak into mic capture.
- Cancelled native GPU kernels can continue executing briefly; generation fencing prevents stale browser output but does not guarantee immediate GPU resource reclamation.
- One voice session and one Work Agent GPU process are suitable for demos, not multiple simultaneous external users.

## Asynchronous work control plane

1. Router identifies the delegated task or job status inquiry.
2. The application creates a schema-validated handoff: objective, conversation summary, allowed tools, requested formats, budget and session scope.
3. The SQLite/WAL ledger records `queued`, stage events, `running`, `completed`, `failed` and cancellation requests. Queue state survives in the database *only while Kaggle disk is retained*.
4. A separately configured Gemini model performs planning and grounded research, subject to server-side permissions and time limits.
5. Local renderers create format-specific documents, visualizations and archive bundles.
6. Structural QA checks artifacts and enforces a completion gate. Rizzler reads stored job events for voice status updates.

### Work-agent constraints

The notebook defaults to a bounded step budget, a single concurrent work worker and a limited output-file budget. It cannot safely run arbitrary shell commands, send email, access private third-party systems or continue after Kaggle is suspended. Scheduled tasks require approval and are dependent on an active server. The source citation quality, visual designs and numerical rigor require case-specific evaluation.

## Missing enterprise boundaries

| Area | Demo now | Required for production |
|---|---|---|
| Authentication | Shared access key | OIDC/OAuth identities and per-user scoped tokens |
| Job ledger | Kaggle SQLite/WAL | PostgreSQL, migration/versioning, idempotent retries |
| Worker queue | Notebook event-loop tasks | Durable broker/queue, worker leases, dead-letter handling |
| Assets | Local ephemeral files | S3-compatible private storage, TTL, encryption, signed downloads |
| Observability | JSONL + dashboard metrics | OpenTelemetry, trace IDs, SLOs, sampling, retention |
| Safety | Limited tool permissions | Fine-grained per-tool scope, prompt-injection testing, malware scanning |
| Model serving | Single Kaggle GPU | GPU deployment with autoscaling and pinned versions |
| Tests | Offline CI | GPU e2e, browser/WebRTC, soak, load and security tests |
| Secrets | Kaggle Secrets | Platform secret manager + rotation + least privilege |

## Deployment recommendation

Kaggle is the **GPU development and showcase environment**; it is not a permanent production server. For Hugging Face Spaces, use a Docker Space for the FastAPI/WebSocket backend and a platform secret for Gemini; reserve appropriate CPU/GPU hardware and configure a trusted external job database/object store. Do not reuse the public Kaggle Quick Tunnel as production infrastructure.
