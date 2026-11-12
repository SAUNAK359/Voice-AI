# Rizzler V11 Phase 3 — Real-Time Voice Intelligence

## Changes

- Version-negotiated WebSocket audio protocol V2; protocol V1 remains backwards compatible.
- Authenticated session generations, ordered input and output PCM16 frames, monotonic timestamps, strict frame sizing, explicit recording invalidation on malformed packets.
- Bounded FIFO inference admission per process; one active native model request, up to eight waiting owners, cancellation-safe timeout, and no duplicated owner admissions.
- ASR final transcription remains the sole authority for tool execution. Optional, off-by-default rolling ASR provides provisional UI-only captions; its snapshots cannot authorize any private writes.
- VoiceEngine validates finalized transcripts, streams text and synthesized audio concurrently, retries invalid/silent TTS once with bounded timeout and rejects repeated failures. Verified tool submission is independent of voice interruption.
- Browser validates output sequence/generation, rejects replay/stale audio, limits buffered WebSocket uploads and playback backlog, exposes degraded HTTPS fallback, detects mic end/device change, and resumes suspended audio after user gesture where permitted.
- Privacy-safe tracing adds opaque trace ID and actual stage timings. It does not log raw PCM. Server-first PCM and browser scheduled playback remain clearly distinct from physical audible playback.
- Frozen evaluator reports per-device/warmth/method p50/p95/p99, counts failed turns in success denominator, and cannot certify physical output from server or browser proxy measurements.

## Transport contract

WS client auth includes protocol=2 and sample_rate. Server answers ready with negotiated protocol.
V2 input: RZV2 magic (4 bytes), generation uint32, sequence uint32, relative timestamp_ms uint32, sample_count uint32, then precisely sample_count PCM16 samples. Each packet carries 1–2048 samples. Generation, sequence, timestamp, size, duration and sample rate are validated. A missing, duplicated, out-of-order or malformed frame invalidates the entire active utterance.

V2 output: RZO2 magic, generation uint32, sequence uint32, sample_rate uint32, PCM16. Browser checks generation before decoding and refuses duplicate/out-of-order audio. Legacy clients continue to receive generation-prefixed PCM16.

## Failure handling and recovery

- No tool/work side effects on interim ASR.
- Model busy or waiting beyond 2.5 seconds: explicit bounded busy response, no blocked queue forever.
- Malformed/out-of-order/truncated audio: reject entire turn; never generate from partial PCM.
- Browser websocket bufferedAmount exceeds budget: interrupt incomplete WS recording, proceed with captured complete utterance over authenticated HTTP fallback.
- Empty/invalid/silent TTS: one safe regeneration; second failure marks the voice turn failed rather than pretending to have spoken.
- Barge-in: stop scheduled audio, increment generation, cancel model/TTS coroutine; native kernel may finish but stale output cannot be played or committed.
- Microphone track loss, revoked permission or audio suspension: display explicit error and reconnect/resume action. No fake listening state.
- HTTP recording is a degraded non-full-duplex transport and must not be described as streaming.
- WorkStore persisted jobs continue during voice interruption. Voice inference fairness is process-local, not a distributed GPU scheduler.

## Test and benchmark contract

Python application regression: tests/test_v11_phase3.py and tests/test_v11_phase3_metrics.py plus existing app tests. Node tests: tests/test_voice_phase3.cjs and tests/test_voice_core.cjs. App CI runs the Python matrix 3.11, 3.12, 3.13.

A frozen real-world dataset can be summarized with:

    python scripts/evaluate_voice_phase3.py --input runs.jsonl --output summary.json

Every sample has a unique ID, device, warm/cold label, outcome, measurement type and observed timing. Failures remain in the denominator. Acoustic qualification can only use qualified physical loopback measurements, minimum 1000 warm turns with >=99% completion and first-audible p95 <= 3000 ms. No simulated measurements are manufactured.

## Production qualification still required

Real Android Chrome and iOS Safari testing, screen-lock/background handling, network re-entry, 100 physically verified interruption trials, 30-minute device soak, real cloud Gemini outages, GPU prewarm/memory/ASR word-error evaluation, MOS listening tests, and physically instrumented audio latency. Passing offline CI and browser scheduling checks is **not** equivalent to those qualifications. RIZZLER_INTERIM_ASR is disabled by default until GPU measurement justifies it. No unmeasured performance or humanlike voice quality is claimed.
