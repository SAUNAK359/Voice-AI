"""Unified voice/tool acceptance: real symbolic checks and local persistent Work jobs."""
from __future__ import annotations
import asyncio
import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

if any(importlib.util.find_spec(x) is None for x in ("pytest","fastapi","numpy","httpx","sympy")):
    raise unittest.SkipTest("Unified integration runs in app CI with Work extras")

import pytest
import numpy as np
from fastapi.testclient import TestClient

from rizzler.math_engine import equation_text, solve_equations
from rizzler.voice_tools import VoiceTools, classify_tool, requested_formats
from rizzler.voice import VoiceEngine, ProviderSet
from rizzler.config import Settings
from rizzler.work_store import WorkStore
from rizzler.api import create_app
from rizzler.speech_text import for_speech

KEY = "unified-voice-key-not-for-production-123456"
SECRET = "unified-voice-signing-key-long-enough-123456"
QUESTION = ("Okay, help me with another problem. If a plus b is equal to root under 7 "
            "and b square is equal to 3 by a, then what is the value of a and b? "
            "Consider even if they're imaginary, I want you to represent imaginary as i.")


def settings():
    return Settings(access_key=KEY)


def test_solve_spoken_complex_system_and_substitute():
    parsed = equation_text(QUESTION)
    assert parsed is not None, parsed
    assert parsed[1] == ["a","b"]
    result = solve_equations(QUESTION)
    assert result["verification"] == "symbolic_substitution"
    assert len(result["solutions"]) == 3
    assert "i" in result["text"] and "|" in result["text"]
    def to_complex(x):
        return complex(x.replace("i","j"))
    for row in result["solutions"]:
        a,b=to_complex(row["a"]),to_complex(row["b"])
        assert abs(a+b-math.sqrt(7)) < 3e-6
        assert abs(a*b*b-3) < 1e-5
    assert "$" not in result["spoken"]
    assert "solution" in result["spoken"].lower()


def test_untrusted_math_cannot_run_python():
    assert equation_text("__import__('os').system('id')") is None
    with pytest.raises((ValueError,SyntaxError)):
        from rizzler.math_engine import _expression
        import sympy as sp
        _expression("__import__('os').system('id')",{"a":sp.Symbol("a")},sp)


def test_precise_routing_and_formats():
    assert classify_tool(QUESTION,True) == "math"
    assert classify_tool("What is the current stock price of Tata Steel?",True) == "web_search"
    assert classify_tool("Search the web for today's news",False) == "web_search"
    assert classify_tool("Can you hear me?",True) is None
    assert classify_tool("What is the difference between NEFT and RTGS?",True) is None
    assert classify_tool("Please create a PowerPoint presentation and PDF report",True)=="work_submit"
    assert classify_tool("Please create a PowerPoint presentation and PDF report",False) is None
    assert requested_formats("Create a PowerPoint presentation and PDF report")==["pptx","pdf"]


def test_unified_work_submission_idempotency_status_cancel(tmp_path):
    store=WorkStore(tmp_path/"work")
    tools=VoiceTools(store,settings())
    async def run():
        requested="Create a PowerPoint presentation and PDF report about rural energy"
        result=await tools.execute(requested,"owner_1",8)
        assert result["verified"] and result["tool"]=="work_submit"
        other=await tools.execute(requested,"owner_1",8)
        assert other["job"]["id"]==result["job"]["id"]
        assert len(store.list_jobs("owner_1"))==1
        status=await tools.execute("What's the progress of my task?","owner_1",9)
        assert "Job queued" in status["text"]
        ended=await tools.execute("Cancel the task","owner_1",10)
        assert ended["verified"]
        assert store.get("owner_1",result["job"]["id"])["status"]=="cancelled"
    asyncio.run(run())


def test_voice_pipeline_uses_math_tool_without_llm():
    class ASR:
        def transcribe(self,wave):return QUESTION
    class LLM:
        async def stream(self,*a):
            raise AssertionError("Model must not hallucinate verified math")
            yield "bad"
    class TTS:
        def synthesize(self,text):
            assert "$" not in text and "\\(" not in text
            return np.ones(2400,dtype="<i2").tobytes()
    async def run():
        engine=VoiceEngine(settings(),ProviderSet(ASR(),LLM(),TTS()),
                           VoiceTools(None,settings()))
        data=[ev async for ev in engine.events(np.ones(16000,dtype="<i2").tobytes(),16000,[],owner="owner_1")]
        types=[event["type"] for event in data]
        assert "tool_result" in types and "audio" in types and "done" in types
        text=next(ev["text"] for ev in data if ev["type"]=="assistant_text")
        assert "Verified solutions" in text
    asyncio.run(run())


def test_speech_never_reads_latex_delimiters():
    spoken=for_speech("Here is $a^2 + b^2 = 7$ and \\(b=2i\\). **Verified**.")
    assert "$" not in spoken and "\\(" not in spoken and "**" not in spoken
    assert "squared" in spoken


def test_voice_owned_work_http_and_upload(tmp_path,monkeypatch):
    monkeypatch.setenv("RIZZLER_WORK_ROOT",str(tmp_path/"work"))
    monkeypatch.setenv("RIZZLER_WORK_SIGNING_KEY",SECRET)
    with TestClient(create_app(settings())) as client:
        headers={"x-rizzler-key":KEY,"x-session-id":"same_owner_123"}
        resp=client.post("/api/voice/uploads",headers={**headers,"x-file-name":"data.csv"},
                         content=b"region,revenue\nNorth,10\nSouth,30\n")
        assert resp.status_code==201,resp.text
        assert resp.json()["ready"]
        assert client.app.state.sessions.get("same_owner_123").uploads
        assert client.get("/api/voice/jobs",headers=headers).status_code==200
        forbidden=client.get("/api/voice/jobs",headers={"x-rizzler-key":KEY,"x-session-id":"other_owner_456"})
        assert forbidden.status_code==200 and forbidden.json()["jobs"]==[]


def test_search_fail_closed_without_key():
    async def run():
        out=await VoiceTools(None,settings()).execute("Current stock price of Tata Steel","owner_1")
        assert out["tool"]=="web_search" and not out["verified"]
        assert "unavailable" in out["text"].lower()
    asyncio.run(run())


def test_search_capability_question_does_not_waste_a_live_query():
    cfg=Settings(access_key=KEY,gemini_api_key="fake-key-not-real")
    async def run():
        tool=VoiceTools(None,cfg)
        reply=await tool.execute("Do you have web search tools?", "owner_1", 5)
        assert reply is not None
        assert reply["tool"]=="web_search"
        assert "search" in reply["spoken"].lower()
    asyncio.run(run())


def test_search_requires_actual_grounding_metadata(monkeypatch):
    from types import SimpleNamespace as NS
    from google import genai
    from rizzler.voice_tools import grounded_search
    class FakeModels:
        async def generate_content(self, **kwargs):
            assert kwargs["config"].tools
            if 'Missing' in kwargs["contents"]:
                return NS(text="A tempting unsupported claim",
                          candidates=[NS(grounding_metadata=None)])
            return NS(text="The quoted value is available in dated sources.",
                      candidates=[NS(grounding_metadata=NS(grounding_chunks=[
                          NS(web=NS(uri="https://example.org/stocks")),
                          NS(web=NS(uri="https://example.org/stocks"))
                      ]))])
    class FakeClient:
        def __init__(self,**kwargs):
            self.aio=NS(models=FakeModels(),aclose=self.aclose)
        async def aclose(self):
            return None
    monkeypatch.setattr(genai,"Client",FakeClient)
    cfg=Settings(access_key=KEY,gemini_api_key="fake-provider-key")
    async def run():
        grounded=await grounded_search("Current Tata Steel stock price",cfg)
        assert grounded["verified"]
        assert grounded["sources"]==["https://example.org/stocks"]
        assert "[Source 1](https://example.org/stocks)" in grounded["text"]
        refused=await grounded_search("Missing source evidence",cfg)
        assert not refused["verified"]
        assert refused["sources"]==[]
        assert "couldn't verify" in refused["text"]
    asyncio.run(run())


def test_search_spoken_ack_precedes_slow_provider_result():
    class ASR:
        def transcribe(self,wave):return "What is the current stock price of Tata Steel?"
    class LLM:
        async def stream(self,*args):
            raise AssertionError("The normal Gemini chat path must not be used for search")
            yield ""
    class TTS:
        def synthesize(self,text):
            return np.ones(2400,dtype="<i2").tobytes()
    class Tool:
        store=None
        async def execute(self,*a,**kw):
            await asyncio.sleep(0.25)
            return {"tool":"web_search","verified":False,
                    "text":"Current price unavailable without verified quote metadata.",
                    "spoken":"I couldn't verify a current exchange quote.",
                    "tool_elapsed_ms":250}
    async def run():
        engine=VoiceEngine(settings(),ProviderSet(ASR(),LLM(),TTS()),Tool())
        result=[e async for e in engine.events(np.ones(16000,dtype="<i2").tobytes(),16000,[],owner="owner_1")]
        names=[e["type"] for e in result]
        assert "tool_result" in names and "done" in names
        assert names.index("audio") < names.index("tool_result"),names
        metrics=next(e["data"] for e in result if e["type"]=="metrics")
        assert metrics["tool"]=="web_search"
        assert metrics["llm_first_text_ms"] is None
    asyncio.run(run())


def test_voice_capabilities_are_owner_authenticated(tmp_path,monkeypatch):
    monkeypatch.delenv("RIZZLER_WORK_ROOT",raising=False)
    monkeypatch.delenv("RIZZLER_WORK_SIGNING_KEY",raising=False)
    with TestClient(create_app(settings())) as client:
        assert client.get("/api/voice/tools").status_code==401
        auth={"x-rizzler-key":KEY,"x-session-id":"owner_1234"}
        response=client.get("/api/voice/tools",headers=auth)
        assert response.status_code==200
        assert response.json()["tools"]["work_agent"]=="disabled"
        assert response.json()["tools"]["symbolic_math"]=="available"
