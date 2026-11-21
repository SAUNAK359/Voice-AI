# V26 Phase 2 — Professional Native Artifact Coverage (Initial Implementation)

**Status:** Implementation started; opt-in and unqualified for production.

## What this change implements
- A separate actual-file content reviewer (`work_outcome_coverage.py`) for native PPTX and DOCX; it does not trust a storyboard's claims of quality.
- The original, approved, **substantive** outcome requirements are the only IDs permitted. Quality and deliverable requirements remain subject to existing structural/final QA.
- The model owns semantic judgment; the runtime verifies exact observed native file excerpts, requirement coverage, strict JSON contract and absence of invented IDs.
- Coverage may be distributed across slides and a detailed Word report. Critical user requirements absent across the complete package block final completion.
- Numeric truth, original evidence provenance, editable chart bindings, rendered-page inspection and checksums remain independent gates.
- New opt-in: `RIZZLER_V26_NATIVE_OUTCOME_QA=1`. Defaults OFF. When enabled, final QA runs paid Gemini review for PPTX/DOCX and blocks unresolved critical coverage. A job without PPTX/DOCX fails closed.
- New regression suite: `tests/test_v26_native_outcome_coverage.py`, included in V26 qualification offline preflight.

## Qualification and known limitations
- Source-exact excerpts show content presence, not factual truth or full visual quality. Independent checks remain necessary.
- Very long Office documents over the complete extraction budget fail closed. Chunked, complete page-by-page coverage remains future work.
- This is only an initial Phase-2 capability increment. More sophisticated authoring, targeted repairs, Voice device testing, blind human content evaluations, and live numeric discrepancy investigation remain open.
- Run live qualification pinned to the exact source commit. Offline unit tests alone do not certify real-model output quality.
- `scripts/qualify_v26_live.py --skip-streamed` is available for a cheaper 4-row and research smoke. It reports `PARTIAL_SMOKE_TEST_ONLY` even on successful partial testing.
- Do not merge or claim production-ready based on CI alone. The final release requires official G00–G17 evidence and operator signoff.
