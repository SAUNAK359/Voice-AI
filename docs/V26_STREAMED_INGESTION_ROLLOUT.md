# V26 streamed Work upload foundation — limited opt-in rollout

This implementation solves the 8 MB Work HTTP memory-buffering constraint for
CSV/XLSX *transport* and private storage. It does not certify 200 MB
downstream analytics or large-file research. Do not promote the high-context
release gate based on upload success.

## Activation and authorization

Set `RIZZLER_V26_LARGE_UPLOADS=1` only for separately qualified deployments.
`RIZZLER_V26_MAX_UPLOAD_BYTES` defaults to 200000000 and must be between
8000000 and 200000000, inclusive. OFF retains the 8 MB byte-buffered API.

Every request uses the existing authenticated Work identity and strict origin
policy. A 0600 randomly named disk staging file receives bounded chunks. SHA-256
is checked at request close, after format inspection, and after the malware scan.
Only regular staging files inside the server-owned private directory are
eligible. Final metadata and private blob are committed under the owner identity.
Per-owner quotas: 30 files and 600 MB total uploaded bytes.

## Production requirements

Production mode wires `scan_clamd_file` for the entire streamed object. Configure
ClamAV StreamMaxLength to cover the configured maximum; scanner errors,
timeouts, unavailable streaming support and infected results all block upload.
Ensure disk-space quota, request-timeout limits, S3 lifecycle policies and
shared-work-volume durability are set by deployment operations. S3 objects
support up to the same 200 MB maximum and are checksum-verified. Staging files
are removed after success or any API-level failure.

## Remaining domain capability boundary

The current Work data-analysis and SQLite/Excel functions cap datasets at
10,000 rows and 50 columns. Upload transport does not override these limits;
very large CSV/XLSX data may be admitted then explicitly fail analysis.
XLSX archives are bounded to 1,000 entries and 400 MB expanded content with
CRC checks, encrypted-entry and external-link/macro rejection. PDF has a
separate existing secure ingestion API.

For high-context RELEASE certification still needed: incremental dataset
profiling/SQL over large sources, XLSX memory/endurance benchmarks, 200 MB
real network upload trials, concurrent quota tests, ClamAV and S3 production
trials, cancellation behavior and incident/rollback evidence. The 18-gate
V26 release verifier remains NOT_READY without these proof receipts.
