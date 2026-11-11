"""Phase-1 regression tests, independent of cloud keys and a physical GPU."""
from __future__ import annotations

import importlib.util
import unittest

if any(importlib.util.find_spec(x) is None for x in ("pytest", "fastapi", "httpx", "numpy")):
    raise unittest.SkipTest("App dependencies are tested in Rizzler App CI")

import asyncio
import wave
import numpy as np
import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from rizzler.api import create_app
from rizzler.config import Settings
from rizzler.qualification import exercise, read_pcm_wav
from rizzler.voice import ProviderSet, VoiceEngine

KEY = "test-qualification-key-please-do-not-use-in-production"


class ASR:
    def transcribe(self, waveform):
        return "Can you provide a short answer?"


class LLM:
    async def stream(self, user_text, history):
        yield "Yes, the application produces real voice samples."


class TTS:
    def synthesize(self, text):
        return (np.ones(2400, dtype="<f4") * 10000).astype("<i2").tobytes()


@pytest.fixture
def app():
    return create_app(Settings(access_key=KEY), ProviderSet(ASR(), LLM(), TTS()))


def test_two_distinct_sessions_connect_concurrently(app):
    with TestClient(app) as client:
        headers = {"origin": "http://testserver"}
        with client.websocket_connect("/ws", headers=headers) as a:
            a.send_json({"type": "auth", "token": KEY, "client_id": "one", "sample_rate": 16000})
            assert a.receive_json()["type"] == "ready"
            with client.websocket_connect("/ws", headers=headers) as b:
                b.send_json({"type": "auth", "token": KEY, "client_id": "two", "sample_rate": 16000})
                assert b.receive_json()["type"] == "ready"
                assert set(client.app.state.sessions.sessions) == {"one", "two"}


def test_same_session_cannot_take_over_connected_websocket(app):
    with TestClient(app) as client:
        headers = {"origin": "http://testserver"}
        with client.websocket_connect("/ws", headers=headers) as a:
            a.send_json({"type": "auth", "token": KEY, "client_id": "same", "sample_rate": 16000})
            assert a.receive_json()["type"] == "ready"
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/ws", headers=headers) as b:
                    b.send_json({"type": "auth", "token": KEY, "client_id": "same", "sample_rate": 16000})
                    b.receive_json()
            assert client.app.state.sessions.sessions["same"].websocket is not None


@pytest.mark.asyncio
async def test_qualification_accepts_actual_fake_audio():
    cfg = Settings(access_key=KEY)
    engine = VoiceEngine(cfg, ProviderSet(ASR(), LLM(), TTS()))
    audio = np.full(16000, 800, dtype="<i2").tobytes()
    result = await exercise(engine, audio, 16000)
    assert result["outcome"] == "ok"
    assert result["audio_bytes"] > 0
    assert "transcript" not in result
    assert result["metrics"]["post_pause_first_audio_ms"] >= 0


def test_wav_validation(tmp_path):
    wav_path = tmp_path / "safe.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 16000)
    raw, rate = read_pcm_wav(wav_path, 22)
    assert len(raw) == 32000 and rate == 16000
    with wave.open(str(tmp_path / "stereo.wav"), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 32000)
    with pytest.raises(ValueError):
        read_pcm_wav(tmp_path / "stereo.wav", 22)
