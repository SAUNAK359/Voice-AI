# Rizzler V11 — Phase 2: Artifact design, verification and recovery

## Execution

Use existing six specialists and WorkStore only. Provider-grounded research and
independently reconciled SQL data feed the content orchestrator or verified
research narrative. Immutable versioned Artifact IR binds title, headings,
complete prose, source URLs, dataset summary SHA-256 and row count. Format
specialists generate real outputs in private, worker-fenced staging.

Before promotion: inspect file integrity, format structure, section/body/source
coverage and native workbook calculations. In strict mode, LibreOffice converts
Word/PowerPoint to PDF, PyMuPDF rasterizes every page and checks bounds, nonempty
text and page counts; Calc recomputes workbook formulas. If deterministic
validation fails, exactly one re-render with the original trusted input is
allowed. Persistent failure blocks completion. No extra model call or external
action is made during repair.

Checks are bound to the generated artifact SHA-256 and persisted with each
specialist result. The master quality gate rechecks bytes and output coverage
before WorkStore can mark the job verified; ZIP bundles include a SHA-256
manifest and are independently checked for member integrity. Existing lease
fences prevent stale workers from overwriting the active checkpoint.

## Delivered formats and checks

| Format | Editable/print output | Quality gates |
| --- | --- | --- |
| DOCX | Semantic heading hierarchy, readable typography, header/footer, compact source-data tables and URLs | Structural integrity, section/body/source parity, rendered pages in strict mode |
| PPTX | Editable elements, continuation slides, source-derived native chart, source hyperlinks and notes | No empty or off-canvas shapes, section/body/source parity, exact rendered-slide count in strict mode |
| XLSX | Formatted Summary/Data/Checks/Dashboard/Sources, charts and native formulas | Source and SQL reconciliation, independent arithmetic; additional Calc recalculation in strict mode |
| PDF | Paginated report, citations and source-derived summary tables | PDF structure and strict text/raster page inspection |
| Other | Existing CSV, JSON, HTML, TXT, MD, PNG, SVG, ZIP outputs | Structure, provenance, hashes, and numeric checks as applicable |

## Production configuration and failure contract

Set RIZZLER_ARTIFACT_QA=strict in production. The Dockerfile installs Writer,
Impress, Calc and fonts; PyMuPDF is an explicit work dependency. Conversion is
bounded with isolated LibreOffice profiles and timeouts. If a required binary
or renderer is unavailable, strict QA fails closed.

Default structural mode does not claim native visual inspection. Both modes
report the selected QA mode and granular results. Malformed input, unsupported
URLs, lost source sections, tampered formulas, changed files, blank/clipped
rendered pages and unreconciled workbook totals block verified completion.
Native renderers may be retried once on deterministic validation errors only;
external provider side effects are never blindly replayed.

## CI and qualification

The App CI matrix covers Python 3.11-3.13, stage/recovery regressions, source
and formula tampering, bounded repair, and cross-format checks. A dedicated
artifact-render-qa job runs actual LibreOffice and PyMuPDF against example
DOCX/PPTX/PDF/XLSX outputs. Release manifest and CodeQL gates remain required.

Remaining release validation is *not* implied by passing CI: blind aesthetic
review, tagged-PDF accessibility, complete contrast checks, evidence-level
fact auditing against independently fetched sources, live cloud-model
benchmarks, cross-device review, and full production restart/restore drills
require separate reproducible evidence. Rasterized pages and text bounds are
useful mechanical tests, not proof of beautiful design or factual correctness.
