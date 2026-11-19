# Rizzler V23 Kaggle Live Failure Analysis — 19 November 2026

## Exact evidence

Archive: `Rizzler_V23_Cognitive_Evidence_20261119_081541_fee79d.zip`  
Tested SHA: `d38e5dfbde88f057e757e3b6d40e3fc50bce57c8`  
Results: **8 PASS / 4 FAIL / 0 SKIP**; preflight model `gemini-3.5-flash-lite` returned valid text.

### Failure 1: Research source acquisition, deterministic TypeError
- Private diagnostics: `research` specialist, `TypeError`, `work_worker.py:174`.
- Root: `sum("blocks" in doc and (doc["blocks"] or doc["tables"]) for doc in retrieved)` may produce a **list** for a successfully extracted source instead of an integer. Python cannot add a list to an integer.
- Repair: central `_usable_source_document` boolean contract, integer counts, success/failure normalization and direct regression.
- The research scenario **must still be retested against real authenticated search and source bytes**.

### Failure 2: Excel analytical studio, deterministic contract conflict
- Private diagnostics: `excel` specialist, `ValueError`, `work_formula.py:97`.
- Root: the legacy verifier rejected **every formula outside the Checks sheet**, whereas the new Excel Studio deliberately generates approved `Study N` formulas.
- Repair: check the generated workbook against the original approved analysis and source values; allow only the expected formula column in approved Study sheets. Reject extra, altered, injected or unsupported formulas.
- Both the renderer preflight and final artifact gate must receive the same verified analysis plan.

### Failure 3: Word editorial model undercoverage
- Private diagnostics: `word` specialist, `ValueError`, `work_editor.py:64`.
- Root: the editorial prompt demanded 330 characters per section and 72% of source text, but the validator also required **at least 450 total words**. A model response can satisfy the prompt and fail validation.
- Repair: express the source-derived minimum explicitly in the model brief; on underlength or schema failure, issue bounded corrective calls with the actual required/observed word count. Preserve source and section lineage; **never silently lower the quality minimum or fabricate content**.
- The editor still fails honestly when the provider cannot deliver compliant, supported content.

### Failure 4: Full repository tests (test-run environment leakage)
- Log: 312 passed, 9 failed, 17 errors, 5 skipped.
- The Kaggle notebook set `RIZZLER_WORK_ROOT` globally but did not provide `RIZZLER_WORK_SIGNING_KEY`. Earlier isolated app and memory tests expect their own default environment, so app startup failed with `Configure both RIZZLER_WORK_ROOT and RIZZLER_WORK_SIGNING_KEY`.
- Repair belongs in the **qualification notebook's test subprocess environment**, not in application security logic. All offline test subprocesses must strip benchmark-only Work roots, credentials, memory and live cognitive switches. Keep the production signing-key requirement intact.
- Recheck full suite after notebook isolation. A green source manifest is not proof that a contaminated test run passed.

## Existing strengths and limitations

- Gemini paid-model preflight passed; the provider was not universally unavailable.
- Offline durable Work completed 8 formats and 7 specialist checkpoints; structural QA passed.
- Live PowerPoint succeeded before Word failed; committed output remains stage-specific.
- Model-directed planning succeeded for the live Work job, but research's planner recorded a schema fallback and Excel's planner hit provider capacity protection.
- Strict visual QA was **disabled**. No claim of fully rendered visual perfection, human-domain correctness, live workflow certification or zero external outages is supported by this ZIP.

## Mandatory next acceptance gates

1. All prior and new regression tests at one immutable source SHA.
2. New Kaggle run with isolated offline suite plus separate, authorized live Gemini/Research/Excel jobs.
3. Inspect independently retrieved research source text and numerical citations, not just provider attribution.
4. Verify Excel native formulas, source values, chart readability, and unapproved formula rejection.
5. Validate real DOCX/PDF/PPTX rendered pages and editorial depth. Structural QA alone is inadequate.
6. Only declare a production-ready outcome after live integration, recovery, authorization, and artifact quality gates are all satisfied.

**Current classification:** source defects identified and repaired on a draft branch; live qualification outstanding.
