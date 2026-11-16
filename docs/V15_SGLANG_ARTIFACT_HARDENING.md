# Rizzler V15 — SGLang specialist inference + unified cognitive reliability

## Architecture

**SGLang is the inference engine for LLM/VLM specialists** (preflight, planning,
independent challenge, research direction, synthesis, PowerPoint storyboard,
recovery, semantic QA, artifact repair, and page-level visual judgment).
SGLang does not replace durable job orchestration, safe tool execution, storage,
or native document rendering. Those remain in Rizzler's Python/FastAPI Work
control plane with fenced leases and validated capability graphs.

This separation is intentional: a fast inference gateway cannot by itself
provide idempotent file publication, independent numerical verification,
owner-scoped authorization or recovery from process crashes.

Supported runtime topology:

    Voice / Work API (FastAPI, always responds 202 to Work submissions)
             |
    WorkStore (durable jobs, approved cognitive plan, receipts, events)
             |
    Model-selected specialist graph + exception-safe parallel execution
       |--- SGLang server /v1/chat/completions (JSON-schema/XGrammar)
       |--- Gemini Google Search grounding tool (optional research retrieval)
       |--- native Word / PowerPoint / Excel / PDF renderers
       |--- independent structural, numerical, visual, semantic QA
             |
    final verified publication (all required outputs must pass)

## Setup

Run an SGLang server separately on an NVIDIA GPU and choose a model with
working instruction following, the required context window and JSON-schema
decoding. Refer to the official SGLang server installation instructions for
your GPU and chosen model; do not install GPU wheels on the voice CPU host.

Example local service (replace model ID with your deployed model):

    python -m sglang.launch_server --model-path Qwen/Qwen3-4B-Instruct-2507 \
      --host 127.0.0.1 --port 30000

Configure the Work worker:

    RIZZLER_AGENTIC_ENABLED=1
    RIZZLER_WORK_LLM_BACKEND=sglang
    RIZZLER_SGLANG_MODEL=Qwen/Qwen3-4B-Instruct-2507
    # Optional: RIZZLER_SGLANG_HIGH_MODEL=<larger-reasoning-model-served-by-SGLang>
    RIZZLER_SGLANG_BASE_URL=http://127.0.0.1:30000/v1
    RIZZLER_V15_COGNITIVE_PREFLIGHT=on
    RIZZLER_V15_RECOVERY=1
    RIZZLER_V15_PRESENTATION=1
    RIZZLER_WORK_ASYNC_WAIT=1
    RIZZLER_ARTIFACT_QA=strict

The endpoint must be local loopback HTTP or authenticated HTTPS. For HTTPS
remote hosting, set RIZZLER_SGLANG_API_KEY as a server-side secret. Requests
never silently fall back to Gemini if the selected SGLang endpoint fails.

For independently reviewed **rendered pages**, use a vision-language model
capable of OpenAI-compatible image inputs. Configure
RIZZLER_SGLANG_VISION_MODEL and RIZZLER_ARTIFACT_QA=agentic. Without a
compatible VLM, agentic image review fails closed; strict QA can still use
independent raster/page checks without a VLM.

Google Search grounding continues to require GEMINI_API_KEY. SGLang is a model
runtime, not a web search service. The SGLang research director decides
questions; Gemini Search retrieves attributable evidence. The final QA never
calls missing citations "verified facts".

## Artifact correctness invariants

- **DOCX:** convert Markdown syntax to native runs, tables and headings.
  Preserve exact whitespace around inline bold/italic/link spans.
- **XLSX:** when the source is an XLSX, use the original workbook as the base;
  retain its original worksheet names and executable formulas unmodified,
  adding report tabs as separate Rizzler-prefixed sheets. Verify each original
  cell and formula by comparison with the uploaded source before publication.
  Fail on reserved report-tab collisions instead of silently renaming formulas.
- **CSV:** legacy report tabs and validated formulas remain unchanged.
- **Finance:** preserve original currency units; apply INR number formats only
  to INR source fields and USD formats only to USD source fields.
- **Parallel specialists:** wait for independent siblings even when one fails;
  preserve the successful siblings' fenced receipts and report the actual failed
  capability, not a secondary cancellation.
- **Decisions:** only allow known, sanitized validation categories into the
  recovery prompt and owner-scoped event log. Never log raw provider error
  bodies or user document text as a diagnostic.
- **Publication:** never publish an incomplete requested artifact bundle.
  Final independent QA still checks source, calculations, file integrity,
  semantic objectives, and (when enabled) rendered-page visual quality.

## Qualification

    pip install -e '.[test,work]'
    python -m pytest -q tests/test_v15_sglang_artifacts.py
    python -m pytest -q tests/test_v15_acceptance_hardening.py
    python scripts/verify_release.py

CI uses a mock SGLang endpoint and native artifact validation. It proves
contracts and integration behavior but **not** live model quality. Before
production release, run a real GPU-backed SGLang model against the original
three Colab acceptance scenarios and inspect the published PPTX, DOCX, XLSX,
PDF, Markdown outputs. Keep the pull request unmerged until this live gate
passes with source-currency and formula fidelity checks.
