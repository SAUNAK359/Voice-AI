# V11 Phase 4 — Native integration hardening (follow-up)

This increment builds on the previously merged native runtime, cognitive
router and opt-in memory implementation in PR #21. It does not replace the
existing WorkStore, agent graph, speech transport or specialist renderers.

## Verified implementation boundaries

1. Gemini receives the complete explicitly supported user request (at most
   8,000 characters). The last user message is no longer silently reduced to
   1,600 characters. Older history remains bounded by the existing context
   selector. Excessively long current requests fail instead of being truncated.
2. The canonical V11 Kaggle notebook verifies authenticated API access,
   native runtime identity and Work Agent wiring, not just unauthenticated
   /ready. It checks that the Work worker is still alive.
3. Notebook model warmup now has an explicit bounded completion gate. Actual
   ASR and TTS model initialization must succeed before claiming the native
   runtime is voice-ready; failure and timeout are visible. Gemini quality
   and microphone-to-speaker latency are not inferred from warmup.
4. Offline integration exercises one real FastAPI authentication ->
   PCM16 voice turn -> permissioned Work submission -> persisted execution DAG
   -> specialist worker -> inspected artifact -> owner-scoped download ->
   voice status and new conversation workflow. The cloud/GPU provider layer
   is replaced by reproducible test doubles only.
5. A separate test verifies private-memory context cannot authorize an
   independent Work submission and that current prompts cannot be omitted.

## Failure matrix and release gates

| Failure | Required result |
| --- | --- |
| Missing/invalid access key | Request rejected |
| Work Agent not attached | V11 launcher fails verification |
| Worker process exited | V11 launcher fails verification |
| ASR or TTS prewarm fails | Launcher refuses voice-ready label |
| ASR or TTS prewarm exceeds deadline | Launcher fails visibly |
| Model request beyond 8,000 characters | Input rejected, not silently shortened |
| Owner B requests owner A's artifacts | Authorization refused |
| Memory contains tool-like instructions | Tool side effects not authorized |
| Voice reset/interrupt after durable work | Persistent work remains intact |
| Artifact QA or persistence fails | No verified completion claimed |

### Automated qualification

Run:
- `python scripts/validate_native_notebook.py`
- `python -m pytest -q tests/test_v11_phase4_integration.py`
- The full existing `Rizzler App CI` Python 3.11-3.13 matrix.

No live cloud credentials or microphone are used by these tests. They do not
establish voice MOS, live Gemini grounding, running T4 inference, actual device
reconnection behavior, secure offsite persistence or p95 first audible sound.
Those remain separate hardware/provider/mobile test gates. Neither Kaggle
ephemeral storage nor this offline suite is multi-tenant production approval.
