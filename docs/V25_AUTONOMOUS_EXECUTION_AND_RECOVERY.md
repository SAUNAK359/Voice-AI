# V25 — Autonomous Artifact Execution and Recovery

This integrates context convergence, format-specific specialists, strict
validators, source-scoped checkpoints and post-render critical reviews.

## Authority
- The LLM chooses cognitive actions: how to group slides, how to revise an
  unsatisfactory output, whether to retry, replan, request evidence or abort.
- The runtime checks immutable user scope, authorized sources, evidence bytes,
  security permissions, budgets, numeric formulas, structural and visual QA.
- No simulated completion: the parent finishes only when every requested
  artifact has a valid hash and the final gate has passed.

## Execution
1. Goal director and data/research specialists produce independently verified
   source facts. Context Intelligence may request bounded backdelegation.
2. Gemini chooses one PowerPoint storyboard or multiple meaningful batches.
   A valid batch plan must cover each original section exactly once.
3. Each batch is independently validated before atomically storing its
   checksum-bound private checkpoint. Up to two batches run concurrently.
4. Reassemble all batches and validate global section coverage, original
   citations, editable slide schema and strict rendered-page bounds.
5. Word/PDF editor and Excel analytical studio use their native format skills
   with the existing source, formula, editable, visual and provenance gates.
6. An independent model reviewer inspects format plans and actual validation
   results to identify material missing content or misleading analysis.
7. On a failure, a specialist LLM chooses rerender, replan, backdelegate or
   abort. No chosen action grants permissions or weakens the validator.
8. The runtime limits the entire repair budget to three decisions per format,
   stores safe typed recovery events and preserves successful siblings.
9. The existing final WorkStore quality gate reopens deliverables and
   revalidates all hashes and source requirements before publication.

## Full-profile feature controls
- RIZZLER_COMPONENT_PLANNING
- RIZZLER_AUTONOMOUS_RECOVERY
- RIZZLER_CANDIDATE_QUALITY

Full mode enables all three. A real Gemini API key must be configured for
model-led cognitive operations. Credentialless offline tests retain only one
bounded structural rerender, never fake model decisions.

## Limits and operational constraints
- Maximum 12 component groups, 8 original sections per group and 36 slides.
- One independent model judgment does not prove factual truth or visual
  superiority. Verbatim quotations prove passage provenance, not facts.
- Passing source-index and QA checks is mandatory; no unchecked content is
  silently delivered if a model cannot converge.
- The host needs LibreOffice Calc for strict spreadsheet recalculation and
  Writer/Impress for visual checks. Provider outages, billing and rate limits
  cannot be eliminated by a code change.
- Source-specific chunk journals are private and never included in public
  evidence bundles.

## Qualification workflow
1. Offline: run v25 autonomy, critical QA and recovery integration tests,
   plus all existing v23/v24 security, WorkStore and artifact tests.
2. Live Kaggle: authorized Gemini API, Internet ON, full Work dependencies,
   LibreOffice Writer, Impress and Calc.
3. Real research -> PPTX, DOCX, PDF, ZIP; separately, clearly synthetic
   quarterly trade CSV -> verified SQL, XLSX, PPTX and ZIP.
4. Confirm actual completed status, requested artifact receipts, cryptographic
   hashes, source/quality reports, real rendered files and independent totals.
5. Export only a sanitized diagnostic JSON and public-only artifact ZIP;
   incomplete/failed jobs are NOT QUALIFIED. Do not mark PR as release-ready
   until the real provider and visual acceptance gates pass.
