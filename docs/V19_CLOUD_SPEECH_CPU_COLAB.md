# Rizzler V19 — Cloud-Native Speech, CPU-only Colab

This branch runs speech inference in Google Gemini, not on the Colab CPU.

- **Realtime conversation**: `gemini-3.8-live` connects via the existing
  authenticated `/ws/live` WebSocket. It accepts 16 kHz PCM audio and
  streams 24 kHz PCM audio; Gemini supplies live speech transcription and
  supports interruption and asynchronous Work-tool handoffs.
- **Legacy HTTP and WebSocket voice**: the default `RIZZLER_SPEECH_BACKEND=gemini`
  uses `gemini-3.5-transcribe` and `gemini-3.8-flash-lite-tts` for
  separate speech tasks. These paths can be slower because transcription,
  reasoning and TTS remain separate remote requests.
- **Historical local voice**: `RIZZLER_SPEECH_BACKEND=legacy_local` and
  `RIZZLER_ALLOW_LEGACY_LOCAL_SPEECH=1` permit old Whisper/Kitten paths.
  Install `.[legacy-local-voice]` explicitly; this is **not** part of CPU Colab.
- **Colab installs**: `pip install -e '.[work,test,mcp,deepagents,voice]'`.
  No local speech weights, CUDA or PyTorch downloads are required.
  LibreOffice and ffmpeg remain useful for **artifact rendering** and
  converting uploaded audio to 16 kHz PCM. This is lightweight CPU work
  relative to running local inference.
- **Separate Work models**: the V18 Work gateway remains
  `gemini-3.8-flash` and `gemini-3.7-flash`, with bounded requests
  and 503 failover. Audio Live is a distinct cloud session.

## Environment
```bash
export RIZZLER_SPEECH_BACKEND=gemini
export RIZZLER_NATIVE_LIVE=1
export RIZZLER_LIVE_MODEL=gemini-3.8-live
export RIZZLER_LIVE_VOICE=Kore
export RIZZLER_CLOUD_STT_MODEL=gemini-3.5-transcribe
export RIZZLER_CLOUD_TTS_MODEL=gemini-3.8-flash-lite-tts
export RIZZLER_CLOUD_TTS_VOICE=Kore
```

## Qualification
1. Run offline provider mocks, release inventory and full test suite.
2. Probe cloud STT/TTS models using synthetic audio **only after permission**
   and with the user-provided API key, recording errors but never secrets.
3. Verify native Gemini Live WebSocket text and real PCM input/output.
   Record model connection, first PCM, first transcript, tool job receipt and
   interruption; do not treat server timing as physical microphone-to-speaker.
4. Run one end-to-end Work artifact, then full ten-task suite.
   Explicitly report failures and unverified sources.

A CPU-only Colab runtime does not remove Google API costs, regional latency
or temporary provider 503 errors. 400–500 ms is a measurement target, not a
guarantee. Synthetic audio-to-audio tests require independent listening
and WER validation before any quality claims.
