# Rizzler V10 — Phase 5 production deployment and acceptance

## Scope and trust model

Phase 5 introduces external OpenID Connect login using authorization-code/PKCE,
server-side revocable hashed sessions, authenticated owner-scoped voice/Work API,
CSRF/origin validation on writes, fail-closed ClamAV upload scanning, HTTPS
reverse-proxy Compose service, health/readiness, process-local operations
telemetry and SHA-256-verified offline backup/restore.

**This is a single-host deployment reference, not a proven multi-region
SaaS release.** Optional PostgreSQL transactional job storage and private
S3-compatible checksum-verified objects are implemented and require live
integration qualification; browser identity sessions remain host-local SQLite,
and the default Compose path uses a shared persistent work-data volume.
Off-host replication, continuous backups and independent model quality are
release gates before distributed production certification.

The old `RIZZLER_ACCESS_KEY` remains **demo-only**. In production mode, it is
ignored for authentication; Work tokens are also ignored and cannot bypass
the OIDC user/session boundary. A user's externally verified OIDC `iss+sub`
pair maps to an irreversible hashed internal owner identifier.

## Prerequisites

- A Linux host capable of running Docker Compose and persistent named volumes.
- Public DNS and ports 80/443 routed to the host (automatic Caddy HTTPS).
- An existing reputable OIDC provider with a registered confidential/web
  client and exact callback `https://YOUR_DOMAIN/auth/callback`.
- Independent randomly generated 32+-byte secrets for work, session and
  operations. **Never reuse** identity-provider or Gemini API secrets.
- The Gemini API key server-side, and real model names confirmed by live tests.
- Adequate CPU, RAM and storage for Whisper, KittenTTS, ClamAV and document tools.
  The supplied Dockerfile is CPU-only; CUDA deployment needs a qualified GPU
  image/host and runtime configuration. No GPU/500-ms guarantee is claimed.

## Quick deployment

1. Copy `deploy/production.env.example` to `.env.production` (gitignored).
   Fill OIDC endpoints from the trusted provider, callback, and all private keys.
   The `RIZZLER_OIDC_REDIRECT_URI` **must** match the publicly served domain.
2. Set `RIZZLER_DOMAIN=your.domain.example` in the Compose shell or private
   Compose environment. Keep secrets out of GitHub Actions logs and commits.
3. Start `docker compose -f compose.production.yml up -d --build`.
4. Confirm `https://YOUR_DOMAIN/ready` returns `{"ready":true,...}`.
   Then test `/auth/login` → provider consent → callback → `/auth/session`.
5. In Work Agent, test upload, scoped job, cancel, status, output SHA-256 and
   cross-user denial. For voice, test mic permission, WSS, HTTPS fallback, barge-in,
   playback and microphone disconnect on the target browser.
6. Configure off-host backup replication and host/Compose supervision alerts
   before accepting business workloads.

The Compose network exposes only Caddy ports; app, worker and ClamAV share a
private network with outbound access for Gemini/OIDC and signature updates.
`RIZZLER_CLAMD_HOST` is set by Compose to `antivirus`. If signatures are
unavailable or scanning fails, upload requests fail closed. A clean ClamAV
result is not a guarantee a document is harmless: parser and sandbox defenses
are also necessary. <https://hub.docker.com/r/clamav/clamav>

## Login and API controls

- `GET /auth/login`: redirect to operator-configured OIDC authorization
  endpoint, PKCE S256 challenge, signed short-lived state/nonce cookie.
- `GET /auth/callback`: exchange code through outbound HTTPS only; validate
  ID token signature via trusted JWKS, issuer, audience, expiry and nonce;
  create opaque `HttpOnly; Secure; SameSite=Lax` session cookie.
- `GET /auth/session`: authenticated identity.
- `POST /auth/refresh`: atomically rotate session; old credential invalid.
- `POST /auth/logout`: revoke current session and clear cookies.
- `POST /api/turn`, `/api/reset`, `/api/interrupt`, all mutating
  `/api/work/*`: authenticated session, matching `X-CSRF-Token`,
  `rizzler_csrf` cookie and trusted public `Origin`.
- `/ws`: same-origin authenticated WebSocket; client-provided IDs cannot
  impersonate another user; voice model still serializes inference.
- `GET /internal/metrics`: operator token only and blocked at Caddy; no
  prompts, raw user IDs or full URLs.
- `GET /health` and `/ready`: nonsecret liveness/readiness.

OIDC authentication does not automatically replace an organization's policies
for identity lifecycle, account deletion, MFA or provider-side revocation. The
signed owner sessions expire after one hour and limit active stored sessions.

## Persistence, backup and recovery

With default settings, `work_data` holds SQLite WAL jobs and identity sessions,
uploads and validated artifacts. The API and worker access the same volume.
Set `RIZZLER_DATABASE_URL` to an authenticated PostgreSQL DSN for a real
transactional job ledger; the optional `postgres` Compose profile runs an
internal PostgreSQL service and requires `POSTGRES_PASSWORD` in the private
environment file (start with `--profile postgres`). Prefer a managed,
backed-up PostgreSQL service for an actual production rollout.

Set `RIZZLER_S3_BUCKET` (and optional region/HTTPS endpoint) to publish
uploads and completed artifacts to a private S3-compatible service. IAM/workload
identity is preferred over static credentials. Server-side AES256 encryption,
size/metadata validation and download SHA-256 checks are applied. When the
verified local copy is missing, the server restores it from remote storage.
Restrict bucket listing/read/write/delete to this deployment's object prefix.
Remote objects are committed before job completion; unreferenced objects can
remain after a failed DB transaction and require a bounded garbage collector.

PostgreSQL and S3 do **not** automatically make this a multi-host deployment:
the OIDC session database is still on the local persistent volume and service
scaling requires separately tested session storage, workers and backup controls.
Fencing prevents stale workers from committing; recovery can retry a model
call, so Gemini billing is **not** exactly once. This topology supports **one
logical host**. Do not scale the API/worker across separate hosts sharing
uncoordinated SQLite files.

For a consistent snapshot, stop **both** API and worker first. Use the same
image and named work-data volume to run the packaged backup module, with an
external backup destination mounted. Example:

```bash
docker compose -f compose.production.yml stop api worker
docker compose -f compose.production.yml run --rm --no-deps \
  --entrypoint python worker -m rizzler.backup backup \
  --root /var/lib/rizzler --archive /backups/rizzler-backup.tar.gz
docker compose -f compose.production.yml up -d api worker
```

Backups verify SHA-256 per file, reject symlinks, and checkpoint WAL databases.
Copy the archive to **encrypted off-host storage**, with independent retention
and verified restoration tests. Local named-volume backups alone are not
disaster recovery.

Restore only to a **new absent destination** while all services are stopped:

```bash
python -m rizzler.backup restore --root /path/to/new-empty-root \
  --archive /path/to/rizzler-backup.tar.gz
```

Then inspect the restored jobs, artifacts and sessions in a staging environment
before swapping volumes or routing real traffic. Key material must be restored
separately from your secrets manager.

## Monitoring and incident response

Readiness checks verify local storage databases; browser microphone, T4 GPU,
Gemini quotas and external OIDC reachability are tested separately. The
`/internal/metrics` endpoint exposes bounded route-class request counts and
HTTP p50/p95/p99 in process memory; it is **not** a durable distributed
metrics system. Collect it into your external monitoring stack and alert on
readiness, error spikes, queue age, worker restarts, storage capacity, scanner
updates, disk utilization, backup freshness and provider quota failures.

For a compromised account: revoke provider access and relevant local sessions;
rotate compromised secrets, disable affected jobs/schedules, preserve audit
evidence under organizational policy and follow data retention requirements.
For corrupt artifacts: deny download and fail safe rather than serving bytes
with invalid hashes.

## Release acceptance checklist

- [ ] Offline app/legacy tests and CodeQL pass at the deployment commit.
- [ ] Container builds reproducibly; Compose configuration, DNS, TLS and WSS
      routes tested with the actual domain and trusted OIDC provider.
- [ ] 2+ genuine user accounts demonstrate zero cross-owner voice/work leaks.
- [ ] Token expiry, rotation, logout, CSRF, authorization-code replay, corrupt
      signing keys, stale browser sessions and OIDC outage tested.
- [ ] Clean and EICAR test uploads exercise the actual ClamAV service; malicious
      archives and ZIP bombs are rejected; signature updates monitored.
- [ ] Worker crash during planning, render and commit resumes/fails safely;
      stale worker cannot commit; repeated scheduled jobs do not multiply.
- [ ] Every requested format rendered and visually reviewed; XLSX formulas
      recalculated; complete files checked against their receipts.
- [ ] Offsite backup + successful isolated restore drill, including jobs and
      ownership checks.
- [ ] Kaggle/native GPU, real Gemini, speech intelligibility, browser barge-in
      and p50/p95/p99 first-audible latency measured on target devices.
- [ ] Representative load, security assessment, license review and operational
      on-call process completed before a public production claim.
- [ ] For multi-host: enable and qualify optional PostgreSQL + S3 adapters,
      replace host-local identity sessions, independently test distributed
      fencing, object garbage collection, backup/restore and tenant isolation.

Do not treat green CI as evidence that unrun external acceptance gates passed.
