# Rizzler V10 — Specialist reliability and voice expressiveness

## Production intent and boundaries

The Voice Agent is the conversation frontend. The Work Agent is the durable
orchestrator and **the only authority** permitted to declare a deliverable
completed. Six curated specialist `SKILL.md` playbooks describe research,
read-only SQL, PowerPoint, Word, Excel and PDF/visual artifacts. A separate
quality stage checks checkpoint integrity, required formats and structural
output content. No specialist may assert its own final parent-job completion.

The six specialists are currently **in-process async units** sharing a fenced
worker and the existing WorkStore—not independent remotely deployed A2A
services or newly exposed MCP servers. That distinction is deliberate:
transport protocols should only be added when there are real independent
networked agents or third-party tools, rather than adding latency and risk.

## Workflow and shared durable state

1. Admission validates identity, idempotency, requested formats and upload
   ownership. The parent job and required specialist rows commit together.
2. A fenced worker claims the job and keeps a 45-second parent lease alive
   with a 12-second heartbeat. Expired claims may be retried up to 3 times.
3. Research and SQL independently acquire evidence in a bounded async group.
   The orchestrator runs after prerequisites. Word/PowerPoint/Excel can overlap
   under a **two-specialist concurrency semaphore** to preserve resources for
   voice traffic. PDF/visual/ZIP runs after those artifacts are committed;
   independent final QA runs last.
4. Every stage has a best-effort target deadline; elapsed stage time and
   breaches are observed from durable start/finish timestamps, not guessed
   percentages. Each stage atomically commits a SHA-256-protected JSON result,
   evidence lineage and its deterministic quality verdict.
5. Native rendering threads write into per-job/per-owner/per-fence staging.
   The only route into shared checkpoints is `agent_publish`, which
   checks the staged SHA-256 and the **current owner, worker and fence inside
   the job transaction**. A timed-out stale renderer cannot overwrite a
   newer committed artifact.
6. The final QA stage verifies every requested receipt, artifact byte hash,
   format structure, relevant semantic checks and evidence lineage.
   Only then does the parent commit publish verified downloadable artifacts.
7. On cancellation/failure/lease exhaustion, pending specialist rows become
   terminal with recorded timestamps; no queued agents are misleadingly
   displayed after the parent has stopped. Interrupted rendered output stays
   unindexed. Background attempt files require retention/garbage-collection
   policy before high-volume deployment.

All status and artifact endpoints are owner-scoped. No model-produced task
claim is a substitute for persisted evidence. Quality reports only show
`completed` when the parent job is actually committed.

## Concrete stage SLAs (targets, not guarantees)

| Stage | Target duration |
| --- | ---: |
| Research | 180 seconds |
| Read-only SQL analytics | 60 seconds |
| Content orchestrator | 150 seconds |
| PowerPoint | 120 seconds |
| Word | 90 seconds |
| Excel | 120 seconds |
| PDF / visualization / package | 120 seconds |
| Independent QA | 45 seconds |

Execution has separate bounded per-stage timeouts. These are **not contractual
SLAs** until measured under representative loads with an agreed percentile,
availability, escalation and cost budget. Real Gemini rate limits, resource
competition and GPU availability can dominate the timings.

## Voice energy and tone

The Rizzler Gemini persona remains concise, curious and energetic while
explicitly avoiding unverified tool-completion claims. KittenTTS now uses
bounded contextual speaking rate: more measured for errors or uncertainty,
lightly more energetic for genuinely verified results, and more deliberate
for questions. This is a limited speed/prosody heuristic, **not** a new
emotion-capable or voice-cloned model. Voice interruptions never cancel
persistent Work jobs unless the user explicitly requests job cancellation.

## Qualification gates

- Worker restart after a completed stage restores the same evidence without
  repeating successful work or reassigning an old fence.
- A timed-out renderer cannot promote a file after its lease has expired.
- Parallel document generation uses independently verified SQL evidence;
  PDF/ZIP QA always sees all prerequisite receipts.
- Cancelled, failed and max-attempts jobs contain no falsely queued specialists;
  no quality endpoint presents pre-publication QA as final success.
- Cross-owner status, source uploads and artifact downloads are rejected.
- The application, legacy, PostgreSQL and CodeQL GitHub checks pass at the
  exact merged commit.

**Important limits:** passing these gates does not establish factual truth,
source freshness, typography/layout excellence or superiority to Claude.
PowerPoint page render/overflow, Word pagination, Excel formula recalculation,
PDF accessibility, externally labelled SQL accuracy and human evaluation remain
necessary for any comparative quality claim. No live cloud-provider or
microphone-to-first-audible performance is asserted from CI.
