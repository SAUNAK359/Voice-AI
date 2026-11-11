# Phase 2 — Real-time voice reliability (implementation and gates)

## Scope

This change hardens the **existing** lightweight browser/WS client: separate
speech-gating state, accurate PCM pre-roll accounting, maximum utterance length,
stale-generation fencing, sequential Web Audio scheduling, cancellation of
scheduled buffers, HTTPS fallback with bounded WebSocket reconnection, track-ended
microphone status, and browser output-start latency estimates.

ASR → Gemini streaming → TTS already overlaps model-output processing and
TTS in `voice.py`. It is **not** an independently proven 500-ms E2E system.

## Latency evidence contract

- `post_pause_first_audio_ms`: server-side PCM production; excludes transport
  and browser output scheduling.
- Browser `output-start proxy`: measured from VAD utterance end to the
  *scheduled* start of the first Web Audio buffer, using a monotonic browser
  clock and the AudioContext timeline. Includes HTTP/WS transit and JS
  scheduling delays. **It is not microphone-to-physical-speaker latency**.
- Browser samples are in-memory only, use nearest-rank p50/p95/p99, bounded
  to 200 completed turns, and omit failed/interrupted turns.
- True acoustic first-audible measurement requires calibrated loopback or
  controlled hardware capture. Do not claim the release target using this proxy.

## Tests and limits

Run `node --test tests/test_voice_core.cjs` and the existing Python tests.
GitHub CI runs these across the application matrix. It cannot measure
on-device noise/echo, accent WER, speech intelligibility or Bluetooth delay.

**Known limitations:** energy VAD remains susceptible to music/TV/noise and
does not distinguish speaker identity; mobile browsers may suspend audio on
screen lock; HTTPS fallback currently buffers the full utterance and is not
low-latency streaming; reconnect resets ongoing WS responses rather than
claiming completion. Professional deployment still requires true per-user auth,
rate limiting, data isolation and durable metrics.

## Acceptance tasks awaiting real devices

1. 100 consecutive barge-in tests with 0 stale audible chunks.
2. At least 20 measured output-start turns each on desktop and mobile plus
   controlled microphone-to-speaker loopback (including p95/p99).
3. Background noise, accents and echo assessment on a labeled audio set.
4. 30-minute continuous session including interruptions, reconnections and
   microphone permission revocations.
5. Live T4 model qualification report using `scripts/qualify_live.py`.

Until recorded, these are **unverified release gates**.
