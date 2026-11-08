# Rizzler V9 — Specialist Skillbook

## What “skilled” means

Each skill has an explicit purpose, formatting or analytical standards, a deterministic execution path where applicable, and a validation policy. Format generation is implemented locally; Gemini composes content and the server controls final job state.

## Skill catalogue

### 01. Evidence Research (`research`)

**Purpose:** source-grounded synthesis.

**Craft contract:** Scope → grounded search → source ledger → dated findings → uncertainty → recommendations.

**Quality gate:** Grounding metadata contains real HTTPS source URLs; factual review remains necessary.

### 02. Analytical Intelligence (`data_analysis`)

**Purpose:** reproducible descriptive statistics.

**Craft contract:** Schema checks, missingness, duplicates, distributions, numeric quality, charts using actual uploaded data.

**Quality gate:** Ownership, numerical finiteness, row counts, no invented observations.

### 03. Editorial PDF Studio (`pdf`)

**Purpose:** premium long-form reporting.

**Craft contract:** Designed cover, editorial chapter hierarchy, page numbers, insight bands, sources and references.

**Quality gate:** Openable multipage PDF, meaningful text and pagination.

### 04. Professional Word Studio (`docx`)

**Purpose:** editable business writing.

**Craft contract:** Document styles, running headers, consistent sections, summary panels, table grids and references.

**Quality gate:** Editable DOCX with valid paragraphs, styles and a readable body.

### 05. Presentation Storytelling Studio (`pptx`)

**Purpose:** executive visual storytelling.

**Craft contract:** 16:9 cover, agenda, section headlines, card layouts, insights, data graphic and sources.

**Quality gate:** Deck opens, no blank slides, conservative text lengths and visible slide numbering.

### 06. Analytical Workbook Studio (`xlsx`)

**Purpose:** real spreadsheet analysis.

**Craft contract:** Executive dashboard, raw data when authorized, data quality, formulas, frozen headers, chart and sources.

**Quality gate:** Workbook opens; sheet formulas, references and chart sources checked.

### 07. Interoperable Data Export (`csv`)

**Purpose:** machine-readable flat table.

**Craft contract:** UTF-8 BOM, consistent rows, explicit headers, formula-injection hardening.

**Quality gate:** CSV roundtrips with stable column counts.

### 08. Structured Results Publisher (`json`)

**Purpose:** portable analytical contract.

**Craft contract:** Versioned metadata, data lineage, typed sections, research sources and references.

**Quality gate:** JSON parses, expected fields and version are present.

### 09. Technical Documentation Architect (`md`)

**Purpose:** readable source-based technical narrative.

**Craft contract:** Overview, contents, H2 sections, key takeaways, source appendix and limitations.

**Quality gate:** Headings and text content are present.

### 10. Digital Report Experience (`html`)

**Purpose:** interactive standalone report.

**Craft contract:** Responsive editorial design, navigation, typography, accessibility and source references.

**Quality gate:** Self-contained valid HTML shell, no remote scripts.

### 11. Insight Visualization Studio (`png`)

**Purpose:** data-grounded raster chart.

**Craft contract:** Readable labels, balanced scale, footnotes, legible fonts and consistent chart styling.

**Quality gate:** Valid raster image and numeric evidence.

### 12. Vector Visualization Studio (`svg`)

**Purpose:** data-grounded vector chart.

**Craft contract:** Scalable typography, explicit titles and accessible annotations.

**Quality gate:** Parsable SVG with accessible title and finite numerical data.

### 13. Plain-Language Briefing (`txt`)

**Purpose:** portable plain text.

**Craft contract:** Scannable headings, short summary, meaningful paragraphs and source notes.

**Quality gate:** Substantive Unicode text.

### 14. Release Packaging Studio (`zip`)

**Purpose:** traceable download bundle.

**Craft contract:** All artifacts, README, per-file SHA-256 manifest and build metadata.

**Quality gate:** No corrupt entries, manifest checksums match content.

### 15. Governed Scheduling Studio (`automation_plan`)

**Purpose:** reviewable recurring jobs.

**Craft contract:** Explicit cadence, consent, opt-in approval, state and execution logs.

**Quality gate:** No recurring run before approval.

### 16. Job Lifecycle Governor (`task_management`)

**Purpose:** truthful progress tracking.

**Craft contract:** Durable job IDs, stage events, retry/cancel semantics, no fabricated status.

**Quality gate:** Completed means all requested artifacts passed checks.

### 17. Voice Operations Interpreter (`voice_status`)

**Purpose:** concise accurate spoken updates.

**Craft contract:** Read actual persisted events and summarize stage, completion, blockers and artifact count.

**Quality gate:** Never invent percentages or claim completion without job state.

## Quality and safety rules

- Gemini model only; API key loaded from Kaggle Secrets on the server.
- Data output charts are derived from uploaded data; missing datasets produce a rejected chart rather than invented results.
- Research requires grounded source URLs from provider metadata; citations and factual correctness still need independent review.
- Required deliverables must exist and pass structural checks before a job can be marked completed.
- ZIP bundles contain a `MANIFEST.json` with SHA-256 checksums and a README.
- Uploaded data access is session-scoped; scheduled actions require approval.
- Full visual and substantive evaluation still requires real-world review; Kaggle sessions are ephemeral.

## Validation performed for this version

- All notebook Python cells parsed and notebook format validated.
- Offline mocked-Gemini jobs for PDF, PPTX, DOCX, XLSX, HTML, SVG/PNG, CSV, JSON, Markdown, TXT and ZIP.
- Authenticated data access and cross-session rejection tests.
- Office/PDF sample rendering and human visual inspection of representative pages.
- XLSX inspection found Executive, Data, Quality and Sources worksheets.
- Live Kaggle GPU inference, real Gemini calls and public network sessions remain unverified.
