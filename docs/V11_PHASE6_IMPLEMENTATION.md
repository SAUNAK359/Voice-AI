# Rizzler V11 — Phase 6 operational hardening and qualification

## Baseline retained
Existing OIDC session validation, CSRF defenses, JWT Work ownership, private
artifact receipts, PostgreSQL transactional job claims, fenced leases,
encrypted image/PDF storage, ClamAV integration, provider model circuits,
strict artifact QA, and process-local metrics remain in place.

## Changes implemented by Phase 6 increment
**Offline backup and atomic restore.** The streaming verified backup includes
jobs.sqlite3, identity.sqlite3, uploads, artifacts, private_memory, visuals,
memory, and pdfs under RIZZLER_WORK_ROOT. Every member has SHA-256 and byte
count recorded; source symlinks and nonregular files are rejected. A restore
extracts into a private temporary staging directory, verifies every byte and
archive member, and atomically renames into the desired previously absent
destination only when fully successful. A bad archive cannot leave a partial
production destination. Backup has no total-size cap: it streams each source
to tar.gz and rehashes to detect changes. The operator MUST stop all API
instances, PDF jobs and workers first; this is an offline snapshot. The archive
contains private state and must be encrypted at rest and access-controlled
outside the application.

**External storage limits.** This offline archive does NOT snapshot externally
configured PostgreSQL databases, S3 object storage, cloud providers, OR
encryption keys stored in environment/secrets managers. Use provider-native
consistent snapshots with coordinated restore points for those dependencies.
If memory/visual/PDF roots are configured outside the Work root, relocate them
under it or back them up separately. Without the original secrets restored
through a secret manager, encrypted PDF/media/memory data cannot be decrypted.

**Bounded PDF admission.** RIZZLER_PDF_MAX_ACTIVE defaults to 2 (allowed 1–8).
The API will not create unlimited in-memory background tasks: new tasks remain
persisted queued and are later picked up by the recovery watchdog. Leases in
the existing SQLite metadata protect parallel workers and checkpoint tiles.
No fixed PDF page count or document-byte limit is introduced. Physical memory,
disk, scanner and cloud resource constraints still apply. Work and voice run
in their existing separate inference/work flows; this is not yet cluster-wide
GPU priority scheduling.

**Optional persistent model call reservations.** Set both
RIZZLER_AI_DAILY_BUDGET_USD and RIZZLER_AI_RESERVATION_PER_CALL_USD plus a shared
persistent RIZZLER_AI_BUDGET_ROOT to opt in. One SQLite BEGIN IMMEDIATE
transaction reserves a configured *conservative estimate* for each Gemini
call, including retries, across voice, vision/PDF-tile research, report
generation and grounded research. Denied calls fail closed before reaching
the provider. Each process must share the same durable budget DB; otherwise
the protection is NOT global. Spending limits are disabled unless explicitly
configured, allowing the customer to pay for large PDFs without an arbitrary
document limit. The reservation represents a deliberately conservative
configuration, not Google's exact billed tokens/currency. Configure actual
Google Cloud/AI Studio billing budgets and alerts independently. The budget
database itself must be snapshotted for continuity.

**Internal operations view.** The existing /internal/metrics requires a
separate independent bearer secret. It now includes the active/allowed
process-local PDF task count and optional global model-call reservation
totals. No prompts, raw tokens, media, IDs, or unredacted provider errors
are included.

## Failure matrix verified by offline tests
- Backup of visual/PDF/memory contents streams without full file read into RAM
- Altered archive member => restore fails and destination does not exist
- Path traversal and symlink source => rejected before restoration
- Atomic restore: successful files are preserved exactly; rerun refuses
  destination overwrite
- Forty simultaneous reservations of a 10-call budget yield at most ten
  accepted requests; cap persists when a new process instance opens the DB
- Budget unset => no artificial client spending cap
- Partial budget configuration and invalid prices => fail closed
- Existing voice/Work/PDF integration tests still pass across Python matrix

## Remaining production qualification
CI cannot prove: real T4 latency under load, priority scheduling between
native GPU kernels and background visual processing, restored PostgreSQL+S3
consistent snapshots, operational key rotation, production malware resistance,
actual cloud billing accuracy, cross-node abuse prevention, incident response,
WAF/DDoS controls, physical device soak, RTO/RPO of a deployed site, or
real-world multi-day 10k-page PDF completion. These require a dedicated
production/staging environment with load generators, fault injection, cloud
billing controls, and measured deployment recovery. Do NOT label Phase 6
production-qualified until those gates pass. The PR's scope is verifiable
single-host operational hardening, not a complete security certification.
