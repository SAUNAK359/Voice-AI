# Engineering improvement plan

## P0 — Blockers before public release

- [ ] Choose a source license and resolve all model/voice third-party licensing obligations.
- [ ] Replace shared global access key with real account login, scoped sessions and permissioned object storage.
- [ ] Add persistent job queue with idempotency and restart recovery; migrate out of ephemeral Kaggle SQLite.
- [ ] Add CSRF/origin policy, CSP without inline scripts, storage quotas, upload validation and retention/deletion controls.
- [ ] Complete Kaggle GPU smoke tests and phone microphone/interrupt QA with redacted evidence.

## P1 — Productization

- [ ] Extract in-notebook service functions into importable, independently testable `src/rizzler` modules.
- [ ] Add config validation and audited model availability checks before serving requests.
- [ ] Add expressive TTS A/B tests and mathematical speech tests rather than simply raising speaking speed.
- [ ] Add dataset-specific analysis validation and slide/page visual QA with actual rendered previews.
- [ ] Deploy a Docker Space with durable database, object storage and authentication.
- [ ] Add an external GPU CI runner and cross-browser audio testing for real barge-in.

## P2 — Enterprise operational excellence

- [ ] OpenTelemetry tracing, SLOs, load testing and benchmark versioning.
- [ ] Policy-as-code on the tool registry and execution audit trails.
- [ ] Integration sandbox for third-party apps and explicit consent for every side effect.
- [ ] Document-grade accessibility, chart source traceability and claim-level citations.
- [ ] Automated generation diffing, visual regression and cost accounting.

## Completed for showcase source package

- [x] Notebook syntax, cell-order and no-FastRTC checks.
- [x] Deterministic session generation/state tests.
- [x] Validated handoff and artifact completion contracts.
- [x] Offline benchmark summarizer and provenance-tagged results.
- [x] Static secret scan and frontend JS syntax checks.

> The source package core contracts are not yet imported by the notebook's GPU runtime. These safeguards become runtime guarantees only after that integration and live testing.
