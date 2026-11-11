# Phase 4 — Durable Work Agent single-host release

## Implemented

- A separate Work Agent worker process and FastAPI endpoints, with signed short-lived owner tokens **independent** of the shared voice key.
- Seventeen registered capabilities (including control-plane skills), twelve real artifact formats, deterministic CSV/XLSX profiling, provider-grounded research that fails closed if citations are missing, and Gemini-generated text.
- SQLite WAL durable job ledger on a persistent volume, owner-scoped uploads/downloads/events, idempotent admission, atomic worker claims, leases, heartbeats and fencing.
- Restart recovery (max three attempts), cooperative cancellation, staged artifacts with SHA256 receipts and verified publication.
- Job dashboard served at /work and explicit automation approval proposals, which do **not** schedule anything automatically.

## Install and run

Install the work extra: `pip install -e '.[voice,work,test]'`.

Set environment: RIZZLER_ACCESS_KEY (voice), GEMINI_API_KEY (server-side), RIZZLER_WORK_ROOT (absolute persistent disk directory), and RIZZLER_WORK_SIGNING_KEY (32+ byte independent random secret).

Run the normal API with `python -m rizzler`. Run a separately supervised process using `python -m rizzler.work_worker --root /srv/rizzler-work`. The root must match the configured API volume. Do not use ephemeral Kaggle directories for durable jobs.

Issue work tokens only after a trusted authentication provider verifies a user. The server exposes no token-minting route. Trusted issuer example:

```python
from rizzler.work_auth import issue_token
token = issue_token(authenticated_user_id, WORK_SIGNING_KEY, ttl=900)
```

## Routes

Bearer owner tokens are required for every /api/work route. The shared voice key never grants work access.

- POST /api/work/uploads: binary CSV/XLSX and X-File-Name header, 8 MB cap.
- POST /api/work/jobs: Idempotency-Key header and JSON {objective,deliverables,uploads}.
- GET /api/work/jobs; GET /api/work/jobs/{id}; GET /api/work/jobs/{id}/events.
- POST /api/work/jobs/{id}/cancel.
- GET /api/work/jobs/{id}/artifacts; GET /api/work/artifacts/{artifact_id}.
- GET /api/work/skills.
- POST /api/work/jobs/{id}/automation-proposals with {cadence_minutes}.
- POST /api/work/automation-proposals/{id}/approve.

## Recovery and correctness

Only the current unexpired fencing token may commit job output. A restart recovers expired running jobs up to three times, and duplicate requests with the same idempotency key return the same job. Exactly-once **committed output** is enforced, not exactly-once provider billing; external effects are disabled. Artifact bytes are SHA256 verified and only owned artifacts are downloadable.

Research requires actual Gemini grounding URL metadata; an ungrounded research request fails. Dataset charts require numeric uploaded data. No fabricated status percentages or sources are permitted.

## Deployment limitations and unresolved acceptance gates

The code is a **single-host release candidate, not production-certified multi-tenant infrastructure**. Public production still needs trusted login/issuer, revocation, storage encryption, malware scanning, file lifecycle policies, backed-up persistent storage and supervised processes. Distributed deployment requires PostgreSQL/managed object storage; SQLite remains per-host. Independently render and visually inspect PDF/DOCX/PPTX/XLSX, verify Office formula recalculation and actual Gemini grounding, complete fault injection and latency/load tests.

The 17 registry entries include task management and voice status. Automatically narrated progress, independently verified 17 specialist models and a 24/7 automation scheduler are **not** claimed implemented. Approved proposals are explicitly marked approved_not_scheduled.

The API is disabled when RIZZLER_WORK_ROOT and RIZZLER_WORK_SIGNING_KEY are both absent and fails startup if only one is present. Offline CI does not prove live Gemini or production quality.
