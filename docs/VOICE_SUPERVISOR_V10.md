# Rizzler V10 — Unified Voice Supervisor acceptance and latency plan

## Why the prior live demo failed

The voice path previously called only `providers.llm.stream(transcript, history)`.
No code connected the voice turns to WorkStore, the grounded search provider,
or a symbolic solver. Gemini text therefore truthfully said it lacked web tools.
The browser rendered raw cumulative text, including `$` and backslash-delimited
LaTeX. Voice generated TTS independently for the same formatted text.

The reported **live user baseline** (seven browser output-start samples) was:
ASR 433.34 ms, Gemini first visible text 8,867.36 ms,
first server PCM 10,889.13 ms, total server 11,914.70 ms.
Browser scheduled-output proxy p50 9,192.8 ms; p95/p99 11,069.7 ms.
These measurements are not physical first-audible latency, do not imply
repeatable percentiles, and are **not** post-upgrade results.

## Implemented system boundary

```text
Authenticated voice session (browser WS/HTTPS)
    → audio decode → Whisper ASR → transcript
    → deterministic low-cost tool selector
         ├ symbolic_math → bounded AST → SymPy solve → substitution proof
         ├ web_search → Gemini google_search → real grounding metadata
         ├ work_submit → owner-bound WorkStore.submit → async WorkWorker
         ├ work_status/cancel → owner-bound persisted job ledger
         └ no tool → Gemini text streaming (same normal path)
    → separate display text + TTS-friendly spoken string
    → streamed PCM / structured transcript / tool results / timings
    → browser rich text renderer + attached Work activity panel
```

The Work Agent and existing six specialist playbooks remain durable and
independent of voice audio interruption. A voice stop **never** automatically
cancels a queued/running Work job. Job cancellation is an explicit command.

This does **not** claim independent A2A network services or a fully implemented
MCP tool registry. The current trusted typed supervisor bridge is a lightweight
single-application control path; specialist tool interoperability can be added
later without introducing new latency on each voice turn.

## Correctness and safe completion

- Mathematical systems are parsed from a *bounded* grammar, not Python `eval`
  or arbitrary model-generated code. Solve a limited two-variable polynomial
  system (degree ≤4) and substitute all candidates into the original equations.
  Complex values are represented using `i`, and unsafe/ambiguous inputs
  fail closed instead of relying on a hallucinated model answer.
- Search requires genuine Google Search grounding metadata and actual HTTPS
  source URLs. No source metadata means **unverified**, not a fabricated quote.
  Financial exchange prices should not be treated as exchange-certified
  real-time feeds.
- Work tasks are submitted with owner bound to the **server-authenticated**
  voice session; the LLM cannot supply another owner's identity. Submission
  uses a per-conversation nonce and turn number for idempotency.
- The integrated interface lists only the current owner's jobs and artifact
  receipts. Uploaded CSV/XLSX datasets are validated by WorkStore, and private
  files remain under authenticated routes.
- Final artifact quality remains limited to the existing deterministic evidence,
  structure and checksum gates; semantic accuracy and aesthetics require
  separate evaluated task benchmarks.

## Latency strategy

Normal requests do not take an additional Gemini planning round trip.
Speech recognition and model use the existing bounded pipelines. The browser
gets bounded UI updates instead of the full growing transcript on each token.
TTS handles short clean phrases and no longer reads literal Markdown math.
Search can overlap its remote request with a brief *truthful* audio acknowledgement.
Long complex ordinary prompts get a non-tool-claim acknowledgement only when
the first Gemini text has not arrived after 1.2 seconds. One-time ASR/TTS
prewarm is opt-in via `RIZZLER_PREWARM=1`, ideally before opening the public UI.

A delayed Google Gemini API response can **still** take seconds. No code change
can honestly guarantee sub-second remote Gemini TTFT; compare after a live
Colab T4 run with cold/warm separation, quota usage, actual provider model,
real microphone timing and network state. The `gemini_first_text_ms` metric
does not represent first audible speech, and tool responses report tool time
instead of mislabeling it as Gemini TTFT.

### Suggested *experimental targets*, not achieved SLAs

| Measurement | Target for next Colab qualification |
| --- | --- |
| Warm ASR p95 | under 800 ms |
| First scheduled playback for verified local math | under 3 s |
| First spoken acknowledgement on slow research | under 3 s |
| Gemini first text (warm, uncontended) | measure p50, p95, p99, not promise |
| Complete Work job | report per-stage deadlines, real duration and receipts |
| Cross-user data isolation | 100% of simulated unauthorized reads rejected |
| Factually valid equation answers | 100% of supported fixture inputs verified |

## Browser behavior

- Streaming plain text and final safe DOM rendering are separate. Final answers
  show real HTML tables, constrained formula display and HTTPS citation links.
  Browser output never evaluates model HTML or JavaScript.
- The voice page contains a compact Work activity section (uploads, state,
  agent steps, verified artifact links). There is no separate Work-page
  navigation; older Work API endpoints remain available for compatibility.
- The server's authenticated capability inventory distinguishes **configured**
  from live-verified external tools. All Work results are persisted and owner
  scoped. A job is only announced completed when WorkStore reports it.
- All work requests remain independent from the single serialized voice
  inference lock; Colab GPU/CPU pressure can still affect real performance.

## Qualification and outstanding limitations

GitHub CI tests cover simulated speech streams, complex symbolic solutions,
Work submission/cancellation/ownership, HTML and JS syntax, safe rich
presentation, and existing PostgreSQL WorkStore contracts. It does not run
the Gemini paid API or microphone capture through a live Colab T4.

Remaining before external production / comparison claims:

1. Live Google Search grounding smoke and full citation tracing on user's key.
2. Measured Colab T4 ASR + TTS warm and cold timings on real audio.
3. Gemini TTFT matrix by model, context length, thinking configuration, quota,
   fallback, and simultaneous work load; preserve failed calls in statistics.
4. True browser first-audible loopback measurements, not proxy timestamps.
5. Multi-session security review with OIDC enabled, not public shared-key demo.
6. Artifact visual page-rendering, factual evidence and hallucination scoring
   against a frozen and independent benchmark (including Claude), with
   blinded human evaluations where quality is subjective.
7. Persistent work volume outside Colab ephemeral storage if artifacts must
   survive runtime shutdown.

**No post-upgrade latency numbers or model-comparison superiority are claimed
until this qualification is executed.**
