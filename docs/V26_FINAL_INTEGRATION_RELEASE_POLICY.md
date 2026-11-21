# V26 Final Integration and Release Qualification

## Scope

This branch starts from the advanced V26 foundation on PR56 at `a88300a7`.
It does **not** replace newer context, reasoning, editorial, dashboard,
multimodal visual or worker implementations with the older pinned V25 code.
An obsolete duplicate branch/PR57 was closed without merging.

### Integrated changes

- `work_consistency.py`: source-fenced, claim-level quantitative consistency
  across actual editable PPTX/DOCX/PDF/XLSX files. Critical PCCF metrics bind
  to original dataset digests, scope and units. Each observed model-extracted
  number must appear in real file text/chart data and equal its independently
  computed Decimal oracle. Unsupported/invented identities and missing
  critical metrics block job completion when explicitly enabled.
- `work_specialists.py`: opt-in execution at the **final** WorkStore QA
  stage. All authorized requested outputs are checked against one PCCF
  graph. Existing user permissions, filename receipts and tool validation
  are not changed. `RIZZLER_V26_CROSS_ARTIFACT_QA` defaults OFF until live
  quantitative and performance qualification.
- `work_release_gate.py`: honest, evidence-based acceptance over the 18
  G00–G17 specification gates. Missing, mismatched or corrupt evidence
  never becomes an automatic PASS. Production qualification requires
  distinct externally signed operator/staging/rollback/human approval.
- `scripts/evaluate_v26_release.py`: explicit CLI to evaluate a complete
  release-evidence directory and emit a truthful JSON decision.
- Dedicated Python adversarial regression tests; all real paid model and
  visual quality benchmarks remain independent release obligations.

## Numerical gate limitations

The text extraction stage inspects native files, and Gemini maps observed
claims to source-computed metrics. The **runtime** verifies mathematical
values, units and period against source receipts. This does not prove every
factual sentence, every potential hallucination, every chart implication or
visual aesthetics. Model claim extraction is fallible. Full semantic
provenance, long-document streaming, negative-claim polarity, rendered-image
audits, analyst calibration and human blind trials remain separate gates.

## Rollout

1. Preserve legacy behavior with all new V26 flags off.
2. Enable the entire PCCF foundation group together, then optionally enable
   cross-artifact QA only when the paid Gemini model, upload format and
   authorized output combination have been qualified.
3. Run WorkStore offline security, SQL and artifact tests on Python
   3.11/3.12/3.13, plus strict LibreOffice QA under the Work-extra environment.
4. Run authenticated live research + Office/Excel jobs and retain sanitized
   proof receipts. A connected API preflight does **not** qualify content.
5. Require G00–G17 evidence and separate operator signoff before
   declaring any production-qualified scope.

## Release CLI

```sh
python scripts/evaluate_v26_release.py \
  --evidence /secure/release-evidence \
  --scope grounded-research \
  --scope editable-office-artifacts \
  --output /secure/RELEASE_DECISION.json
```

The CLI exits nonzero if release is not production-qualified. The private
`RIZZLER_RELEASE_VERIFICATION_KEY` must be injected only by trusted release
operations; never place it in Kaggle, notebooks, logs or artifacts.

## Status

Offline CI results and commit digests must be fetched from GitHub Actions
at the exact head SHA. Release gates without genuine evidence remain
`NOT_RUN`. User-authorized production deployment is **not** performed
as part of this branch. 
