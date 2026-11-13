# Rizzler V12 — Release acceptance matrix

This is a falsifiable engineering tracker, not a completion certificate.
The only valid status is OBSERVED when accompanied by an actual passing run;
code presence or proposed architecture does not establish production fitness.

| Feature | Code state | Qualification state |
| --- | --- | --- |
| Model-selected tool planning | V12 AgentRuntime | Offline mocked tests; real Gemini pending |
| Multi-step tools and concurrent reads | Bounded controller | Offline mocked tests; live latency pending |
| Voice / chat shared Work owner | API + VoiceEngine | Offline TestClient; live OIDC pending |
| Work acceptance and persistent worker | V11 WorkStore reused | Existing V11 tests; restart soak pending |
| Cancel / revise / retry | Durable approval, immutable lineage | Offline tests; live UI/microphone pending |
| Work plans, status, events, artifacts | Existing private APIs + agent adapters | Owner isolation tested; live sync pending |
| Text and microphone access | Main app with text-only option | JS syntax tests; real device pending |
| Work deliverable quality | V11 strict structural/render QA | Objective-quality and market-data truth gaps |
| Real external source verification | Provider-grounded metadata | Independent source/claim audit pending |
| Long-running dynamic DAG | V11 fixed specialist graph | NOT IMPLEMENTED |
| Arbitrary MCP and browser actions | Explicitly untrusted/unavailable | NOT IMPLEMENTED |
| Persistent cognitive execution state | Durable Work jobs only | Full agent-turn checkpointing NOT IMPLEMENTED |
| Self-improving procedural memory | Existing opt-in memory, no autonomous writes | NOT IMPLEMENTED |
| Latency and voice quality | Existing V11 streaming | Phone acoustic p95 benchmark pending |
| Claude competitiveness | No reliable measured comparison | NOT VERIFIED |
| Production incident/security readiness | Existing V11 checks + V12 owner controls | Penetration, IdP, scale, recovery gates pending |

For each release candidate:
1. Run and archive exact SHA + all GitHub check conclusions.
2. Independently execute a signed-in Voice → Work submission → worker →
   artifact QA → download → revision → cancel/retry → job replay exercise.
3. Run at least 100 realistic held-out multi-tool scenarios, no fabricated
   tool outputs, with owner isolation, injection, failure and concurrency tests.
4. Test at least 30 real grounded research calls and independently audit claims.
5. Benchmark voice on actual phone/browser hardware under concurrent Work load.
6. Evaluate real Office/PDF artifacts, formulas, source truth and layout.
7. Compare to one pinned Claude configuration with equivalent tools and budgets.

Do not mark V12 as fully production-ready until all relevant mandatory gates
have evidence attached to a release commit.
