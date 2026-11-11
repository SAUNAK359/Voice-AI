"""Phase-2 server streaming regressions: mocked providers, no network or GPU."""
from __future__ import annotations

import asyncio
import importlib.util
import unittest

if any(importlib.util.find_spec(x) is None for x in ("numpy", "pytest", "fastapi", "httpx")):
    raise unittest.SkipTest("Phase-2 server tests run in app CI")

import numpy as np

from rizzler.config import Settings
from rizzler.voice import VoiceEngine, ProviderSet

KEY = "phase2-test-private-key-not-for-production"
PCM = np.full(16000, 450, dtype="<i2").tobytes()


class ASR:
    def transcribe(self, waveform):
        return "Tell me one thing."


class TTS:
    def synthesize(self, text):
        return np.full(2400, 500, dtype="<i2").tobytes()


class StreamingLLM:
    def __init__(self):
        self.audio_seen = asyncio.Event()

    async def stream(self, text, history):
        yield "This is the first sentence to stream. "
        await asyncio.wait_for(self.audio_seen.wait(), timeout=4)
        yield "Here is the second sentence."


def test_tts_emits_audio_before_llm_stream_finishes():
    async def run():
        llm = StreamingLLM()
        engine = VoiceEngine(Settings(access_key=KEY), ProviderSet(ASR(), llm, TTS()))
        items = []
        async for event in engine.events(PCM, 16000, []):
            items.append(event["type"])
            if event["type"] == "audio":
                llm.audio_seen.set()
        assert llm.audio_seen.is_set()
        assert items.index("audio") < items.index("done")
        assert "metrics" in items and items[-1] == "done"
    asyncio.run(asyncio.wait_for(run(), timeout=6))


def test_generation_error_does_not_return_private_tts_exception():
    class BrokenTTS:
        def synthesize(self, text):
            raise RuntimeError("internal API token should stay private")
    class SingleLLM:
        async def stream(self, text, history):
            yield "This is a complete answer for the user."
    async def run():
        engine = VoiceEngine(Settings(access_key=KEY),
                             ProviderSet(ASR(), SingleLLM(), BrokenTTS()))
        events = [e async for e in engine.events(PCM, 16000, [])]
        errors = [e for e in events if e["type"] == "error"]
        assert len(errors) == 1
        assert "internal API token" not in str(errors)
        assert not any(e["type"] == "done" for e in events)
    asyncio.run(asyncio.wait_for(run(), timeout=5))


def test_stream_cancellation_stops_completion_and_releases_producer():
    class PausedLLM:
        def __init__(self):
            self.started = asyncio.Event()
        async def stream(self, text, history):
            self.started.set()
            await asyncio.Event().wait()
            yield "Should never be heard."
    async def run():
        llm = PausedLLM()
        engine = VoiceEngine(Settings(access_key=KEY),
                             ProviderSet(ASR(), llm, TTS()))
        async def consume():
            return [e async for e in engine.events(PCM, 16000, [])]
        task = asyncio.create_task(consume())
        await asyncio.wait_for(llm.started.wait(), timeout=3)
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=3)
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled stream was allowed to complete")
    asyncio.run(asyncio.wait_for(run(), timeout=6))
