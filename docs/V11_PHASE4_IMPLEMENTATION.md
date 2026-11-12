# Rizzler V11 — Phase 4: Unified runtime and controlled intelligence

## Scope implemented

Phase 4 unifies the app launch path and introduces privacy-aware, explicitly
opted-in long-term memory while retaining the existing Phase 1 task planner,
Phase 2 artifact QA, Phase 3 versioned voice protocol and durable Work Agent.

- **Canonical native Kaggle launcher:** `notebooks/Rizzler_V11_Unified_Native_Kaggle.ipynb`
  obtains approved secrets through Kaggle Secrets, retrieves the specified
  Git revision, installs the native package, enables CUDA Whisper, launches
  `python -m rizzler` and the separate `rizzler.work_worker` process, and
  verifies `/ready` before reporting startup. It never spins up the old V9
  notebook-local FastAPI server. The observed Git SHA is printed, not assumed.
- **Conversation context governor:** newest turns plus relevance-matched older
  turns, chronological order, strict text and token-proxy bounds, no invented
  summaries, excluded tool/system messages. User-saved context is kept distinct.
- **Opt-in private memory:** `RIZZLER_MEMORY_ENABLED=1` requires an independent
  32+ character key and absolute persistent root. Entries are encrypted at
  rest with AES-256-GCM, scoped by authenticated owner, bounded to 24 facts
  and expire after 30 days. Voice commands or owner-authenticated endpoints
  are required to write/delete. **No automatic extraction** from conversation.
- **Memory behavior:** explicit `remember that ...`, `what do you remember
  about ...`, `list my memories`, `forget memory <id>`, and
  `forget all my memories` (followed by `confirm delete all memories` within 30 seconds). Recalled statements are untrusted context for
  Gemini, not instructions or tool authorization; LLM-only context retrieval
  is bounded and cannot execute Work Agent actions.
- **Frontend:** one optional Saved memory control to inspect, save and delete
  entries. The control stays hidden when memory is disabled. The existing
  voice and background Work UI and authentication flow are preserved.
- **Failure handling:** missing or reused encryption key, unauthenticated
  access, malformed memory input, tampered ciphertext, wrong-owner deletion,
  corrupt sources and absent storage fail closed; a memory retrieval failure
  degrades to ordinary conversational inference instead of breaking voice.
- **Existing cognitive orchestration:** Gemini adaptive fast/deep/guarded
  routing, model fallback, token quotas, tool permission registry, source
  provenance, specialist plans, cancellation, and WorkStore recovery remain
  authoritative. No additional unverified model agents were introduced.

## Environment and security

```ini
# Disabled by default.
RIZZLER_MEMORY_ENABLED=0
# Configure only after explicit user choice:
# RIZZLER_MEMORY_ENABLED=1
# RIZZLER_MEMORY_ROOT=/var/lib/rizzler/private_memory
# RIZZLER_MEMORY_KEY=<independent secret >=32 characters>
```

The demo access key does not prove unique identity. Encrypted memory in demo
mode is therefore additionally blocked unless
`RIZZLER_DEMO_MEMORY_SINGLE_USER=1` is explicitly set by the operator for
a single-user, non-shared notebook. Do not enable it on a public shared demo.

Production authentication still requires the established OIDC and CSRF
controls. Do not turn on long-term memory for shared demo-key sessions:
demo `x-session-id` values are not durable authenticated human identities.
Deletion removes application records and future retrieval, but may not
immediately purge encrypted bytes from SQLite WAL, backups or filesystem
snapshots; configure backup retention and cryptographic key lifecycle.

## How to launch

For Kaggle, upload the new **V11 native** notebook, enable a NVIDIA GPU and
Internet, and configure Kaggle Secrets `GEMINI_API_KEY` and
`RIZZLER_ACCESS_KEY`. Run cells in order. The notebook intentionally uses
session-ephemeral storage and does not enable a public tunnel automatically;
connect to phones only with a trusted authenticated HTTPS/WSS proxy. Preserve
the printed Git revision in benchmark records. Use the production Docker
Compose setup and an off-host persistent database/object store for actual
durable deployment, not Kaggle `/working` storage.

For a local host, run `pip install -e '.[voice,work]'` and
`pip install -r requirements-identity.txt`, configure validated secrets,
then separately supervise `python -m rizzler` and
`python -m rizzler.work_worker --root /absolute/work/root`.

## Offline tests

```bash
python scripts/validate_native_notebook.py
python -m unittest tests.test_v11_phase4_native
python -m pytest -q tests/test_v11_phase4.py
node --check src/rizzler/web/app.js
```

The legacy V9 notebook remains an archived, independently tested demo and
should not be represented as the V11 unified runtime. Existing legacy
notebook snapshot tests remain unchanged.

## Remaining external qualification gates

CI can verify native process wiring, permissions, memory isolation, byte
integrity, deterministic context selection, mocked voice/tool integration and
the existing artifact/work regression suite. CI **cannot** prove:

- Kaggle GPU image installs and native Whisper/KittenTTS audio produce
  correct real speech in a fresh account/session
- Gemini model names, quotas, web grounding and response quality are usable
  with actual credentials
- physical speaker-to-microphone audio latency, barge-in under echo or iOS
  Safari microphone suspension recovery
- actual off-host persistence/backups, OIDC provider enforcement, workload
  capacity, secure deletion from off-host backups or human accessibility QA

A production release must obtain redacted, reproducible evidence for each
applicable gate; no offline mock is accepted as live qualification.
