# Rizzler V23 — HACE / Deep Agents / LangMem deployment qualification

**Status: release candidate; deployment is NOT approved by this document.**
This branch builds on V22 and must be merged together with its upstream V20,
V21 and V22 prerequisites. Do not mark CI success alone as proof of live cloud
provider integration or finished artifact quality.

## Runtime architecture

- **Voice:** Gemini Live retains its own real-time transport and capacity.
- **Work:** LangGraph dependency execution with immutable model-authored plan,
  WorkStore worker leases, specialist checkpoints and final publication gate.
- **Inference:** Gemini Work gateway has an operator-maximum three in-flight
  model requests, adaptive provider error backpressure, RPM/estimated TPM
  counters. Provider quotas and external HTTP 503s are not eliminable.
- **HACE:** L0 global requirements, domain branches, bounded L1..L7 deeper
  specialized analytical stages and bottom-up reconciliation. The LLM supplies
  inspectable analyses, NOT private chain-of-thought. Source references can
  only come from the job's authorized source inventory.
- **Capabilities:** Only host-registered tools can be discovered, compiled or
  executed; run independent read-only operations concurrently. The default
  registry includes source inventory, passage lookup and curated skill
  references. It is not unrestricted computer/browser execution.
- **Agent packages:** Eight dedicated SKILL.md plus manifest.yaml bundles
  for research, SQL, synthesis, PowerPoint, Word, Excel, PDF/visual and Quality.
  Manifest validation can only reduce, never grant, permissions.
- **Memory:** Existing encrypted user preferences coexist with separately
  encrypted operational lessons. LangMem extraction is optional, after
  completed verified work, based only on QA-observed issues. Work recall uses
  lexical retrieval with no hot-path LLM calls, never source fact verification.
- **Artifacts:** Existing format-specific renderers and independent QA/rebuild
  remain the only path to publication. HACE results are unverified analytical
  hypotheses unless checked against primary evidence.

## Dependency installation

```bash
python -m pip install -e '.[test,work,deepagents]'
```

Do not run in an unauthenticated public process. Use an owner-scoped Work
authorization environment and durable data directories. The distinct
RIZZLER_MEMORY_KEY must be a secret injected by the hosting provider, not
committed to Git.

## Conservative enablement

```bash
RIZZLER_WORK_LLM_BACKEND=gemini
RIZZLER_WORK_ORCHESTRATOR=deepagents
RIZZLER_WORK_PROVIDER_PARALLEL=3
RIZZLER_WORK_PROVIDER_ADAPTIVE=1
RIZZLER_WORK_CONCURRENCY=1

RIZZLER_HACE_ENABLED=1
RIZZLER_HACE_EXECUTE_STAGES=1
RIZZLER_DEEP_AGENTS_SYNTHESIS=1

RIZZLER_MEMORY_ENABLED=1
RIZZLER_LANGMEM_ENABLED=1
```

Also configure GEMINI_API_KEY, RIZZLER_WORK_ROOT, RIZZLER_MEMORY_KEY,
RIZZLER_ARTIFACT_QA=strict, and the deployment's actual verified Google
quota limits RIZZLER_WORK_PROVIDER_RPM/TPM. One Work job can still fan out
into three inference calls; total jobs concurrency is a different limit.

Keep HACE stage execution disabled for low-complexity requests if measured
extra inference cost outweighs the additional analytical depth. No fixed
word or keyword router is required; the model-authored DAG is bounded by
the host contracts.

## Required release gates

1. Python 3.11/3.12/3.13 CI and App CI including V20-V23 tests green.
2. CodeQL and production configuration checks green.
3. Installed package contains eight SKILL.md and eight manifest.yaml files.
4. No active worker can publish an artifact without passing the existing
   final fenced Quality gate. Reboot/retry preserves stage checkpoints.
5. Validate source-policy restrictions, cross-owner memory isolation,
   corrupt-checkpoint rejection and secret/PII exclusion.
6. Live paid Gemini run: authorized web research, long PDF, rich editable PPT,
   DOCX, XLSX, ZIP, QA repair, Live voice handoff and all outputs downloadable.
7. Visual inspection of *actual* rendered artifacts (not structural checks
   alone), factual claim-source checks and accurate numeric reconciliation.
8. Load test at one/two/three Gemini Work requests, with injected 429/503,
   latency, provider RPM/TPM budget, cancellation, process restart and retry.
9. Check P50/P95 time to first progress, total task completion, grounded
   information density, context compression effect and job failure counts.
10. Review private-source permissions, installed MCP scopes, runtime network
    egress, object-store access, encryption key management and audit logging.

## Known remaining limitations

- This PR is not proof that Rizzler beats Claude on objective benchmarks.
- The current Capability Fabric has vetted read-only tools, not arbitrary
  shell/browser/infrastructure privileges or all possible integrations.
- LangMem consolidation learns QA-grounded procedural lessons; it is not
  continuous automatic learning from every conversation or a trained model.
- HACE stage analyses are model-authored, not independent proof of factual
  correctness. Provider-attributed URLs still require source-level verification.
- No live paid Gemini or on-device latency benchmarks are included in
  no-credential CI. Production readiness requires real E2E release evidence.
- High-performance distributed inference admission across different hosts
  without a shared Work gateway still needs a true distributed coordinator.
