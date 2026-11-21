# V26 out-of-core analytics — integration, limitations and qualification

## What was implemented

The feature-gated `RIZZLER_V26_STREAM_ANALYTICS=1` opt-in routes the
Work Agent's uploaded CSV/XLSX through a private temporary disk-backed SQLite
index rather than the existing 10,000-row in-memory analytics limit.
Validated read-only aggregate SQL can inspect the complete dataset, and
model-guided SQL exploration reuses the established bounded query schema,
critic and source experiment IDs. Critical numerical facts are computed
independently with Decimal and include source SHA-256, row counts and
explicit limitations.

The SQL specialist persists only source-bound aggregate receipts, not the
private on-disk SQLite database or raw input rows. Dataset parsing rejects
inconsistent row lengths, malformed encoding, nonfinite numeric measures,
unsafe source links, oversized cells, excessive rows and oversized temporary
storage. The full original upload digest is rechecked after ingestion.

The artifact strategy preserves the original user task and the V26 editorial
context. Word/PDF/PowerPoint are authored from source-bound summaries, without
passing fabricated full-source rows to their renderers. A requested XLSX is a
*full-source derived metric profile*, explicitly **not** a replacement copy of
every input row. Published numeric cells and source digests are reopened and
reconciled against the full-source oracle. Requested CSV from CSV source is
byte-preserving, while XLSX-to-CSV full-file conversion remains unqualified
and fails rather than corrupting the source bytes.

## Operator activation

```sh
export RIZZLER_V26_LARGE_UPLOADS=1
export RIZZLER_V26_STREAM_ANALYTICS=1
export RIZZLER_V26_MAX_UPLOAD_BYTES=200000000
```

Both switches are default OFF. Never turn on all V26 cognition flags in an
unqualified production deployment merely because this feature exists.
Separate production ClamAV file scanning, owner quotas, WorkStore lease
fencing, external storage and identity rules remain mandatory.

## Actual large-file bench (operator must execute)

```sh
python scripts/qualify_v26_large_data.py \
  --source /secure/test-fixtures/validated-200mb.csv \
  --min-bytes 190000000 \
  --max-seconds 600 \
  --max-rss-mb 1024 \
  --output /secure/v26-evidence/streaming-200mb.json
```

This outputs a hash-bound, content-free JSON receipt with actual elapsed
time and Linux process high-water memory. A synthetic or smaller input is
not mislabeled as a completed 200 MB trial. Run with multiple fixtures,
XLSX workloads and representative concurrency; a single benchmark cannot
qualify p95 or worst-case memory.

## Explicitly unresolved release work

- 200 MB end-to-end network, malware scanner and S3 pressure tests; 5M-row
  and 1.4 GB temporary-DB budgets must be measured on actual deployment disks
- Rich domain-specific statistical/supply-chain/engineering methodology for
  large sources (one-pass exact totals are not causal or statistical proof)
- Full-source *semantically relevant* charts, robust XLSX formula-backed
  source-data models and qualified large-file CSV conversion
- Independently measured Gemini 429/503 reliability and multi-format live
  output quality, with real model IDs, token/cost measurements and artifacts
- Frozen >=120 cross-domain suite, blind professional reviews, security
  injection/chaos tests, staging migrations, rollback and operations signoff

The V26 G00-G17 release decision is still NOT_READY unless the exact
candidate SHA has real evidence for every applicable release gate.
Do not claim the release is 95% reliable without representative measured
tasks, uncertainty bounds and human review.
