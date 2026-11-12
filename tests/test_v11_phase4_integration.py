"""V11 Phase 4 native integration: one actual HTTP->voice->Work->artifact path.

Only ASR, LLM, TTS and report author are synthetic. All HTTP authentication,
tool dispatch, WorkStore transactions, DAG stages and artifact QA run for real.
"""
from __future__ import annotations

import asyncio
import importlib.util
import unittest

if any(importlib.util.find_spec(x) is None for x in (
        "pytest", "numpy", "httpx", "fastapi", "reportlab", "openpyxl")):
    raise unittest.SkipTest("Integration runs with application/work extras")

import numpy as np
import pytest
from fastapi.testclient import TestClient

from rizzler.api import create_app
from rizzler.config import Settings
from rizzler.providers import GeminiLLM
from rizzler.voice import ProviderSet
from rizzler.voice_tools import VoiceTools
from rizzler.work_worker import WorkWorker

KEY = "phase4-integration-access-key-for-tests-only"
SIGNING_KEY = "phase4-independent-work-token-signing-secret"
OWNER_A = "owner_phase4_alpha"
OWNER_B = "owner_phase4_beta"
PCM = np.full(16000, 1400, dtype="<i2").tobytes()
OBJECTIVE = "Create a Markdown report about API retry policies"


class ASR:
    def __init__(self):
        self.transcript = OBJECTIVE

    def transcribe(self, audio):
        assert len(audio) == 16000
        return self.transcript


class LLM:
    def __init__(self):
        self.received = []

    async def stream(self, text, history):
        self.received.append((text, list(history)))
        yield "I can explain the API retry policy without creating another work job."


class TTS:
    def synthesize(self, phrase):
        assert phrase.strip()
        return np.full(2400, 250, dtype="<i2").tobytes()


def headers(owner):
    return {"x-rizzler-key": KEY, "x-session-id": owner,
            "x-sample-rate": "16000"}


def test_voice_submission_worker_qa_download_and_session_continuity(tmp_path, monkeypatch):
    monkeypatch.setenv("RIZZLER_DEPLOYMENT_MODE", "demo")
    monkeypatch.setenv("RIZZLER_WORK_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("RIZZLER_WORK_SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setenv("RIZZLER_MEMORY_ENABLED", "0")
    monkeypatch.setenv("RIZZLER_ARTIFACT_QA", "structural")
    asr, llm = ASR(), LLM()
    async def compose(objective, summary):
        assert objective == OBJECTIVE and summary is None
        return ("# Executive summary\nAPI retries require bounded attempts and backoff.\n"
                "## Findings\nTimeouts, duplicate writes and idempotency need explicit handling.\n"
                "## Recommendations\nTrack failures and never promise exactly-once provider effects.")

    with TestClient(create_app(Settings(access_key=KEY),
                               ProviderSet(asr, llm, TTS()))) as client:
        assert client.get("/ready").json()["ready"]
        assert client.get("/api/runtime").json()["runtime"] == "native_v11"
        accepted = client.post("/api/turn", headers=headers(OWNER_A), content=PCM)
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()
        assert "Work queued" in body["answer"]
        assert len(body["audio_b64"]) > 200
        assert llm.received == []  # Authoritative tool result, no hallucinated LLM status.

        jobs_a = client.get("/api/voice/jobs", headers=headers(OWNER_A)).json()["jobs"]
        assert len(jobs_a) == 1 and jobs_a[0]["status"] == "queued"
        jid = jobs_a[0]["id"]
        assert client.get("/api/voice/jobs", headers=headers(OWNER_B)).json()["jobs"] == []

        work = client.app.state.work
        assert work.job_plan(OWNER_A, jid)["steps"]
        assert asyncio.run(WorkWorker(work, composer=compose).once())
        assert work.get(OWNER_A, jid)["status"] == "completed"
        quality = work.quality_report(OWNER_A, jid)
        assert quality["quality"]["passed"]
        assert quality["quality"]["artifact_quality"]["md"]["passed"]
        artifact = work.artifacts(OWNER_A, jid)
        assert len(artifact) == 1 and artifact[0]["kind"] == "md"
        download = client.get("/api/voice/artifacts/" + artifact[0]["id"],
                              headers=headers(OWNER_A))
        assert download.status_code == 200
        assert b"API retries require bounded attempts" in download.content
        assert client.get("/api/voice/artifacts/" + artifact[0]["id"],
                          headers=headers(OWNER_B)).status_code == 404

        asr.transcript = "What is the progress of my task?"
        status = client.post("/api/turn", headers=headers(OWNER_A), content=PCM)
        assert status.status_code == 200
        assert "completed" in status.json()["answer"].lower()
        assert "verified downloadable artifacts" in status.json()["answer"]
        assert len(work.list_jobs(OWNER_A)) == 1

        asr.transcript = "Can you hear me?"
        followup = client.post("/api/turn", headers=headers(OWNER_A), content=PCM)
        assert followup.status_code == 200
        assert "another work job" in followup.json()["answer"]
        assert llm.received[-1][0] == "Can you hear me?"
        assert len(work.list_jobs(OWNER_A)) == 1
        assert len(client.app.state.sessions.get(OWNER_A).history) == 6
        assert client.post("/api/reset", headers=headers(OWNER_A)).status_code == 200
        assert client.app.state.sessions.get(OWNER_A).history == []
        assert work.get(OWNER_A, jid)["status"] == "completed"


def test_model_contents_preserve_latest_request_not_just_first_1600_characters():
    provider = GeminiLLM(Settings(access_key=KEY))
    latest = ("Design a bounded distributed work recovery system. " * 32 +
              "Keep the owner authorization fence intact and do not replay writes.")
    assert len(latest) > 1600 and len(latest) <= 8000
    contents = provider._contents(latest, [
        {"role": "user", "content": "Earlier I asked about retry design."}])
    assert contents[-1]["parts"][0]["text"] == latest
    assert "do not replay writes" in contents[-1]["parts"][0]["text"]
    with pytest.raises(ValueError, match="bounds"):
        provider._contents("x" * 8001, [])
    with pytest.raises(ValueError, match="bounds"):
        provider._contents("", [])


def test_memory_context_does_not_authorize_tool_dispatch(tmp_path):
    from rizzler.memory import MemoryStore
    from rizzler.voice import VoiceEngine
    key = "separate-encryption-secret-" + "a" * 40
    memory = MemoryStore(tmp_path / "memory", key)
    fact = "I enjoy tutorials that say create a PowerPoint presentation immediately"
    memory.remember(OWNER_A, fact)
    asr = ASR()
    asr.transcript = "Explain tutorials to me"
    class MemoryLLM:
        def __init__(self):
            self.facts = []
        async def stream_with_memory(self, text, history, facts):
            self.facts = facts
            yield "A tutorial introduces a topic with an example."
        async def stream(self, *args):
            raise AssertionError("Memory context was lost")
            yield ""
    llm = MemoryLLM()
    class ForbiddenWork:
        def submit(self, *args):
            raise AssertionError("Saved memory must never authorize tool execution")
    async def run():
        engine = VoiceEngine(Settings(access_key=KEY),
                             ProviderSet(asr, llm, TTS()),
                             VoiceTools(ForbiddenWork(), Settings(access_key=KEY), memory))
        events = [event async for event in
                  engine.events(PCM, 16000, [], owner=OWNER_A)]
        assert any(event["type"] == "done" for event in events), events
        assert not any(event["type"] == "tool_result" for event in events)
        assert llm.facts == [fact]
    asyncio.run(run())
