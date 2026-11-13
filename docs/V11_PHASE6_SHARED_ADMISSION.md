# V11 Phase 6 — Shared authenticated-owner admission hardening

This increment extends merged Phase 6 PRs #25 and #26; it does not replace the existing private OIDC sessions, JWT Work identity, WorkStore leases, encrypted PDF checkpoints, disaster recovery, or optional AI billing reservations.

## Implemented scope

- Optional shared 60-second fixed-window SQLite admission ledger, keyed by HMAC-SHA256 of **verified** session/Work owner IDs. No subject strings, bearer credentials, filenames, prompts, document paths or response bodies are persisted by the limiter.
- One `BEGIN IMMEDIATE` transaction admits or rejects requests atomically across API/Work processes sharing the exact same durable database. Unauthenticated requests never consume another owner's allowance. The Work bearer-token surface retains its independent authorization.
- Separate per-owner classes for ordinary API calls, expensive analysis, Work writes, PDF chunk uploads and WebSocket connections. `429` responses include a Retry-After header; exhausted WebSocket connection class closes with retryable code 1013.
- The private operations endpoint exposes only aggregate counters and configured budgets, not per-owner identities; the readiness endpoint checks the admission table when configured.
- Opt-in environment configuration: `RIZZLER_ADMISSION_ENABLED=1`, an **independent** `RIZZLER_ADMISSION_SECRET` (32+ bytes), and a shared absolute `RIZZLER_ADMISSION_ROOT`. Adjustable per-minute rates: `RIZZLER_RATE_STANDARD_PER_MIN`, `RIZZLER_RATE_EXPENSIVE_PER_MIN`, `RIZZLER_RATE_UPLOAD_PER_MIN`, `RIZZLER_RATE_WORK_PER_MIN` and `RIZZLER_RATE_CONNECT_PER_MIN`. Defaults respectively 1200, 90, 3600, 60, 90. Invalid configuration fails at startup.
- No fixed PDF page count, total PDF bytes, or report-model token budget is introduced. Large uploads can be throttled or temporarily delayed, not silently truncated. Expensive questions should be queued asynchronously using the already-implemented durable PDF research pipeline.

## Failure and security tests

`tests/test_v11_phase6_admission.py` verifies transaction safety with 40 simultaneous attempts across four ledger objects; exactly the configured owner allowance succeeds, another owner is unaffected, and distinct route classes are isolated. It checks HMAC-private database subjects, rate rollover, wrong credentials, owner isolation, Work bearer tokens, WebSocket admission and startup configuration rejection. Run in the existing Python 3.11/3.12/3.13 app matrix.

## Deployment caveats

The limiter is **disabled by default** until the operator explicitly enables it, to avoid introducing a hidden production limit without capacity measurements. It is a per-owner fixed-window limiter, **not** a global DDoS/WAF/IP perimeter, model-slot scheduler, GPU admission control, Google actual-charge meter, or account-wide quota. If API nodes use different SQLite volumes, protection is only per-volume rather than global; for multiple hosts use a truly shared transactional database or a dedicated distributed rate-limiter. Fixed windows can allow bursts at minute boundaries. Real denial-of-service penetration tests, resource exhaustion drills, multi-node pressure tests, replay/refund accounting, secrets rotation and cloud billing verification remain release gates.

## Production qualification status

The merged Phase 6 baseline supplies offline backup/restore, bounded background task scheduling, provider reservations, worker fencing and health checks. This additional increment adds owner-level shared API pressure protection. Full production certification still requires external IdP, WAF and networking controls, real GPU/mobile performance, load tests under authenticated production sessions, persistent cross-node storage and live disaster-recovery RTO/RPO evidence.
