# Rizzler V15 Cognitive Preflight

## Execution sequence

**Understand → Anticipate → Plan → Self-evaluate → Execute → Verify**

Rizzler is a model-led Work Agent, but an LLM has no authority to waive security,
source policy, file integrity, supported tool contracts, or user authorization.

1. **Understand:** Gemini interprets the complete task, audience, requested
   artifacts, source restrictions, and explicit success criteria. Source content is
   treated as untrusted data; uploaded documents are not assumed to be accurate.
2. **Anticipate:** Gemini identifies missing evidence, source ambiguity,
   incorrect units, dependencies, risks, and mitigations. Nothing has executed yet.
3. **Plan:** Gemini selects registered specialists and an efficient DAG, including
   parallel paths and appropriate model thinking levels.
4. **Self-evaluate:** Gemini checks its understanding, evidence policy, graph,
   source needs, and completion criteria. An **independent second model call**
   reviews the complete preflight and approves or returns actionable feedback.
   The director can revise the entire proposal up to three times. A rejected
   proposal never silently falls back to a keyword-derived plan.
5. **Execute:** The approved graph is atomically installed under a fenced worker
   lease. The worker executes asynchronously with durable checkpoints and
   registered tools. The existing bounded, model-guided specialist retry remains
   available. External side effects are limited to authorized tools.
6. **Verify:** Existing structural, numeric, evidence and visual checks still
   apply. Cognitively approved jobs also require independent semantic review of
   the original objective **and** the approved success criteria; two content
   repairs may occur before final publication.

## Durability and privacy

The full schema-validated preflight is hashed, owner-scoped, and persisted in
the `cognitive_preflights` SQLite table. Retrieval validates its checksum,
authorization, schema, user-specified deliverables, attachments, and source
policy. A worker that crashes after preflight but before execution recovers
the same approved plan, avoiding a second model decision with different tools.

Only final goal, success criteria, risk mitigations, chosen tools, dependencies,
and independent review summary are visible at
`GET /work/jobs/{id}/cognitive-preflight` (relative to the mounted Work API).
The endpoint never exposes hidden model reasoning or provider credentials.

`RIZZLER_V15_COGNITIVE_PREFLIGHT=on` enables the cognitive pathway by default
for new agentic Work jobs. Set `off` for the previous model-led DAG adapter.
Completed and previously committed jobs keep their original plan and
checkpoints. The Work API still submits jobs asynchronously and returns HTTP
202. `RIZZLER_WORK_ASYNC_WAIT=1` removes application-imposed model timers, not
provider failures, user cancellations, worker leases, quotas, or safety gates.

## Operational acceptance

Run:

```bash
pip install -e '.[test,work]'
python -m pytest -q tests/test_v15_cognitive_preflight.py tests/test_v15_acceptance_hardening.py
python scripts/verify_release.py
```

Then complete the provider-backed Colab acceptance package and inspect all native
PPTX, DOCX, XLSX, PDF and Markdown artifacts. A successful offline run does **not**
establish factual correctness or professional visual quality; release requires
an independent live research-to-artifact benchmark and review of revisions.

A short-lived provider outage can still fail an individual attempt.
"Fully agentic" here means the model drives reasoning and workflow decisions,
not that the LLM can execute arbitrary code or bypass trusted policies.
