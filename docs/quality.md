# Quality and acceptance matrix

| Boundary | Deterministic check | Still needs live review |
| --- | --- | --- |
| Notebook | Syntax, metadata, execution order, required warmups present, no FastRTC | Actual GPU imports and inference |
| Browser | JS syntax and voice/work route binding references | Browser mic, TLS/WSS, autoplay, barge-in |
| Security | No committed keys/outputs, constant-time auth helper, safe filenames | Penetration test, scoped identities, prompt injection |
| Work Agent | Schema shape, permissions, bounded budgets, artifact completion | Real Gemini output, tool-call robustness, research accuracy |
| Reports | Format-specific generation and structural validation | Editorial layout, source truthfulness, print rendering |
| Slides | PPTX generation / nonblank slides | Visual hierarchy, chart interpretation and overflow |
| Excel | Workbook data / formulas / chart source checks | Formula recalc, analytic validity, large data stress |
| Benchmarks | Missing observations stay missing, successful-only aggregates | V9 measured GPU, phone and concurrent workloads |

## Release gates

CPU CI green is a necessary source-quality gate only. A public product release additionally requires: successful fresh Kaggle GPU setup from zero state, valid model responses and audio output, responsive phone microphone, no stale audio after interruption, successful research with verifiable sources, real file downloads, sustained worker operation, retry/reconnect testing, security review, latency metrics with adequate sample sizes, and intentional licensing.
