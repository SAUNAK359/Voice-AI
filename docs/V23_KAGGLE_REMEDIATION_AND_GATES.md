# V23.1 Kaggle Failure Remediation — evidence and release gate

**Scope:** targeted code corrections for the actual Kaggle ZIP `Rizzler_V23_Cognitive_Evidence_20261119_065940_f23020 (1).zip`. The uploaded evidence has six PASS and five FAIL checks, with 329 passed/2 failed repository tests and an Excel-only live job failing before the Excel agent runs.

## Proven findings

- A full-mode Excel-only job erroneously persisted `research_synthesis:true` even though its authorized task DAG did not contain `research`. The orchestrator demanded non-existent research lineage and failed before the Excel specialist began. Fixed by enabling research synthesis **only when the requested deliverables contain `research`**.
- Category-free workbook aggregation was allowed in the Gemini studio planning validator but rejected by the sheet executor. Fixed `_studies` to accept `category=None` for overall `SUM`, `AVERAGE` and `COUNT` formulas.
- The cookie-tampering regression test mutated a cookie while leaving its original scoped cookie in the HTTP client. The test now replaces the cookie; the real HMAC authentication check is unchanged.
- Live Gemini and research tests emitted only `execution_error`; the evidence ZIP lacks the underlying provider/contract exceptions. Added owner-scoped private, sanitized diagnostic traces at both individual specialist and parent job failure boundaries.
- Worker inference previously limited simultaneous Gemini calls but lacked a shared requests-per-minute gate. Added SQLite-backed, model-scoped sliding-window admission across workers, configured using `RIZZLER_GEMINI_RPM`; per-attempt quota reservations now occur when the request is admitted. Provider availability still cannot be guaranteed.

## Failure diagnostics

Authenticated endpoint: `GET /jobs/{jid}/diagnostics?after=0`

Each row contains stage, safe category, exception type/module, source-code filenames/line numbers and a stable fingerprint. **Never include raw exceptions, prompts, document text, API keys, URLs, source snippets or stack locals** in the diagnostics response. The WorkStore ledger enforces owner scoping. Retryable provider errors, invalid schemas and internal contract failures are separate categories, so the next Kaggle run can identify actual root causes.

## Mandatory validation

1. Run repository CI and production suites at the **exact head SHA**, including the spreadsheet Work extras and existing owner-isolation tests.
2. Re-run Kaggle live Gemini content, grounded research and sample Excel jobs. Capture `diagnostics`, `agent_steps`, `cognition`, source receipts and precise file QA. Keep real credentials out of export bundles.
3. Re-run the full research→multi-artifact job with strict visual QA, compare actual page/slide content, data units, citations and formula results.
4. Inject 400/401/429/503, malformed JSON, broken URLs, corrupt spreadsheets and cancellation; record actual recovery behavior and latency.
5. Only then evaluate production readiness. The fixes and passing repository CI **do not** establish perfect live provider availability, factual accuracy, end-to-end zero-failure guarantees or artifact aesthetics.

**Release decision:** Keep PR draft until live evidence verifies the workflows. No unsupported promise of zero failures.
