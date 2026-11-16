# Rizzler V15 — MVP implementation and release qualification

**Status:** implementation branch; merge only after all CI gates and user-run
live acceptance. A working orchestration platform cannot guarantee that every
external research query, inference provider or arbitrary file will succeed.

## What is implemented

| Layer | Production approach |
|---|---|
| Identity | Shared OIDC owner session for Voice and Work; private Work artifacts |
| Cognitive plane | Schema-constrained Understand → Anticipate → Plan → Independent Review, approved durable plan, model-driven recovery with shared bounded job snapshot |
| Inference | Gemini or SGLang OpenAI-compatible structured LLM/VLM endpoints; GPU server is a separately deployed service |
| MCP | Official MCP SDK v2 private stdio server, signed owner identity, read-only by default, explicit opt-in to Work submission |
| Web research | Gemini Google Search grounding with LLM-selected queries and HTTPS attribution; no unsupported claim that URLs verify page contents |
| Source ingestion | Work Studio uploads CSV/XLSX analytics and indexed reference documents; 200 MB chunked source transport with SHA256 and explicit source coverage |
| Specialists | model-approved graph, bounded concurrent jobs and specialist parallelism, independent checkpoints and recovery; source-specific numeric checks |
| Artifact output | Native PPTX/DOCX/XLSX/PDF, HTML/Markdown/CSV/JSON/SVG/PNG/TXT and ZIP with strict receipts |
| QA | structural/native page checks, exact data and formulas, semantic critique, bounded model-directed repair, verified all-format publication |

## Setup

Install the Work platform and optional MCP SDK:

\`\`\`bash
pip install -e '.[work,test,mcp]'
\`\`\`

The application stays on its persistent filesystem and fenced worker ledger.
Configure an authorized inference service and the optional research provider.
To run SGLang behind a private GPU Docker network:

\`\`\`bash
export RIZZLER_SGLANG_MODEL='Qwen/Qwen3-4B-Instruct-2507'
export RIZZLER_SGLANG_API_KEY='<a-secret-you-created>'
docker compose -f compose.production.yml -f compose.sglang.yml config
docker compose -f compose.production.yml -f compose.sglang.yml up -d
\`\`\`

GPU compatibility, available image versions, secrets, memory and model cache
must be qualified on the chosen host. The SGLang server is not bundled into the
application Python wheel. Inference APIs stay private; no SGLang public port.

The worker's \`RIZZLER_WORK_CONCURRENCY\` is 1..8 (default 1). More workers
increase simultaneous provider calls and native rendering load, not per-model
accuracy; benchmark throughput before raising it. Multi-host deployments need
a shared PostgreSQL ledger, shared persistent artifact storage and safe
quota coordination. The Compose reference is one-host only.

**External web research requires \`GEMINI_API_KEY\` even when the cognitive
backend is SGLang.** SGLang serves the research director's LLM; the actual
source-grounding tool is Gemini Search.

## MCP owner-scoped tools

Start a private local stdio process only after authenticating the user with a
trusted external login/issuer. The issuer may produce a short-lived scoped token:

\`\`\`python
from rizzler.work_auth import issue_token
# The authenticated backend—not an anonymous tool caller—sets the owner.
token = issue_token(owner="authenticated_owner", secret=signing_secret, ttl=900)
\`\`\`

The process receives \`RIZZLER_MCP_SIGNING_SECRET\`,
\`RIZZLER_MCP_WORK_TOKEN\`, and \`RIZZLER_WORK_ROOT\` from secure server-side
configuration. Launch \`python -m rizzler.work_mcp\` over stdio using the MCP
client. Default \`RIZZLER_MCP_ALLOW_WRITE=0\` exposes only owned listing,
plans, preflight, agent progress, events, artifacts and quality. Explicit
\`RIZZLER_MCP_ALLOW_WRITE=1\` enables a submit-only private Work tool; no
arbitrary file, shell, database, browser or other external write tools.
User-created requests do not grant MCP permissions.

The Work API and voice controller already use shared owner identity; the MCP
stdio adapter has an independent trusted token boundary. No public MCP server
or automatic exchange of a voice key for private Work access is implemented.

## Work Studio

- The 8 MB CSV/XLSX input is for SQL analytics, not arbitrary files.
- Reference documents can be uploaded and indexed separately. Transfers over
  8 MB use SHA256-checked 1 MiB chunks, up to 200 MB per file.
- The Work form exposes selected source IDs, targeted/complete indexing
  coverage and external-research policy.
- The authenticated \`GET /api/work/readiness\` reports **configuration-only**
  availability, never a successful provider health check.
- \`POST /api/work/jobs\` accepts \`source_ids\`, \`source_coverage\`,
  \`evidence_scope\`, uploads, requested formats and an idempotency key.

## Verification

Offline tests (no provider calls or outside facts):

\`\`\`bash
python -m pytest -q tests/test_v15_mvp_mcp_scale.py
python scripts/qualify_mvp.py --offline --output /tmp/rizzler-mvp-offline
python scripts/verify_release.py
\`\`\`

The test runner produces \`MVP_ACCEPTANCE_REPORT.zip\`, including per-agent
timelines, checksums, proof of publication and generated files. Synthetic
evidence in offline mode must NEVER be presented as verified live research.

For the user's **actual acceptance**, set a working Gemini Search key, select
a capable model backend and install LibreOffice/PyMuPDF. Use strict/agentic QA,
then run:

\`\`\`bash
python scripts/qualify_mvp.py --output /tmp/rizzler-mvp-live
\`\`\`

Upload the ZIP for inspection of official Indian trade research and the
complete financial multi-format package. Require all requested native
artifacts to be actually downloadable, source-grounded, numerically
consistent, rendered/readable, and correct in original currency and formulas.

## MVP boundaries (no false production claims)

- Provider-generated citations are **attributed, not page-fetched verified**.
  Independent retrieval, detailed fact audit and human review remain necessary
  for high-stakes claims and current economic statistics.
- The source reader handles bounded CSV/XLSX analytics; 200 MB is the source
  indexing limit, **not a promise of SQL joins over 200 MB**.
- Native code/build artifact generation and arbitrary third-party action
  execution are outside this registered artifact catalog. The model cannot
  invent new tool permissions to claim success.
- Visual quality is evaluated through native render checks and optional VLM
  review; human editorial/design assessment is still needed.
- SGLang model quality, GPU throughput, OIDC setup and live web-provider health
  cannot be inferred from offline CI.
- Run backup/restore, concurrent-user stress, provider outage, cancellation,
  restart and fault-injection tests on the production host before merge.

This release keeps safety, ownership, immutable source formulas, and accurate
failure reporting above superficial "always succeeded" status flags.
