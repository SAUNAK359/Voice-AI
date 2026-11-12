"""Phase 3 tests: offline bounded real-time protocol, queue, voice and recovery."""
from __future__ import annotations

import asyncio
import importlib.util
import struct
import unittest

if any(importlib.util.find_spec(x) is None for x in ("pytest","fastapi","numpy","httpx")):
    raise unittest.SkipTest("Voice realtime tests run with app/test extras")

import numpy as np
import pytest
from fastapi.testclient import TestClient

from rizzler.api import create_app
from rizzler.config import Settings
from rizzler.sessions import FairInference, AdmissionBusy
from rizzler.voice_protocol import (AudioFrameState, FRAME_MAGIC, VERSION,
    OUTPUT_MAGIC, INPUT_HEADER, output_packet)
from rizzler.voice import VoiceEngine, ProviderSet

KEY = "v11-phase3-test-private-voice-key"
PCM = np.full(16000,1200,dtype="<i2").tobytes()


def frame(generation=1,seq=0,timestamp=0,samples=640):
    return INPUT_HEADER.pack(FRAME_MAGIC,generation,seq,timestamp,samples) + (
        np.full(samples,1200,dtype="<i2").tobytes())


def test_frame_protocol_fails_closed_on_duplicates_cross_turn_and_overflow():
    state=AudioFrameState(1,16000,2)
    assert len(state.receive(frame()))==1280
    for packet in (frame(),frame(seq=2),frame(generation=2,seq=1),
                   frame(seq=1,timestamp=0,samples=0),
                   frame(seq=1,samples=3000),
                   frame(seq=1)[:-2],
                   frame(seq=1,timestamp=6001)):
        with pytest.raises(ValueError):
            state.receive(packet)
    assert len(state.receive(frame(seq=1,timestamp=40)))==1280
    assert state.next_seq==2
    oversized=AudioFrameState(1,8000,1)
    for seq in range(3):
        oversized.receive(frame(seq=seq,timestamp=seq*80,samples=2048))
    with pytest.raises(ValueError,match="duration"):
        oversized.receive(frame(seq=3,timestamp=240,samples=2048))
    encoded=output_packet(1,0,24000,np.full(240,dtype="<i2",fill_value=12).tobytes())
    assert encoded[:4]==OUTPUT_MAGIC and struct.unpack_from("<III",encoded,4)==(1,0,24000)
    for bad in (b"", b"\x00"*3, b"\x00"*6000):
        with pytest.raises(ValueError):
            output_packet(1,0,24000,bad)


def test_admission_is_fifo_owner_isolated_bounded_and_cancel_safe():
    async def run():
        pool=FairInference(max_waiting=2)
        events=[]
        release=asyncio.Event()
        async def first():
            async with pool.permit("a",timeout=2):
                events.append("a")
                await release.wait()
        a=asyncio.create_task(first())
        await asyncio.wait_for(wait_for(lambda:pool.locked()),1)
        async def later(name):
            async with pool.permit(name,timeout=2):
                events.append(name)
        b=asyncio.create_task(later("b"))
        await asyncio.wait_for(wait_for(lambda:pool.queued==1),1)
        with pytest.raises(AdmissionBusy):
            async with pool.permit("b",timeout=.1):
                raise AssertionError("Duplicate owner was admitted")
        c=asyncio.create_task(later("c"))
        await asyncio.wait_for(wait_for(lambda:pool.queued==2),1)
        with pytest.raises(AdmissionBusy):
            async with pool.permit("d",timeout=.1):
                raise AssertionError("Bounded admission queue overflow")
        release.set()
        await asyncio.gather(a,b,c)
        assert events==["a","b","c"]
        assert not pool.locked() and pool.queued==0

        release.clear()
        a=asyncio.create_task(first())
        await asyncio.wait_for(wait_for(lambda:pool.locked()),1)
        b=asyncio.create_task(later("z"))
        await asyncio.wait_for(wait_for(lambda:pool.queued==1),1)
        b.cancel()
        with pytest.raises(asyncio.CancelledError):await b
        assert pool.queued==0
        release.set()
        await a
    asyncio.run(run())


async def wait_for(predicate):
    while not predicate():
        await asyncio.sleep(.002)


class ASR:
    def transcribe(self,wave):
        return "Please explain the result"


class LLM:
    async def stream(self,text,history):
        yield "The result is described by the following verified summary."


class TTS:
    def synthesize(self,text):
        return np.full(2400,300,dtype="<i2").tobytes()


def test_versioned_websocket_takes_sequenced_frames_without_losing_history():
    cfg=Settings(access_key=KEY)
    with TestClient(create_app(cfg,ProviderSet(ASR(),LLM(),TTS()))) as c:
        with c.websocket_connect("/ws",headers={"origin":"http://testserver"}) as ws:
            ws.send_json({"type":"auth","token":KEY,"client_id":"phase3v2",
                          "sample_rate":16000,"protocol":VERSION})
            ready=ws.receive_json()
            assert ready["protocol"]==2 and ready["type"]=="ready"
            ws.send_json({"type":"speech_start","generation":1})
            assert ws.receive_json()["type"]=="status"
            for i in range(25):
                ws.send_bytes(frame(seq=i,timestamp=i*40))
            ws.send_json({"type":"speech_end","generation":1})
            audio_seq=0
            received=[]
            for _ in range(100):
                msg=ws.receive()
                if msg.get("bytes") is not None:
                    b=msg["bytes"]
                    assert b[:4]==OUTPUT_MAGIC
                    assert struct.unpack_from("<III",b,4)==(1,audio_seq,24000)
                    audio_seq+=1
                else:
                    import json
                    event=json.loads(msg["text"])
                    received.append(event["type"])
                    if event["type"]=="done":break
            assert audio_seq and "transcript" in received and "done" in received
        assert len(c.app.state.sessions.get("phase3v2").history)==2


def test_versioned_websocket_rejects_tampered_and_future_frames():
    cfg=Settings(access_key=KEY)
    with TestClient(create_app(cfg,ProviderSet(ASR(),LLM(),TTS()))) as c:
        with c.websocket_connect("/ws",headers={"origin":"http://testserver"}) as ws:
            ws.send_json({"type":"auth","token":KEY,"client_id":"badframe",
                          "sample_rate":16000,"protocol":2})
            assert ws.receive_json()["type"]=="ready"
            ws.send_json({"type":"speech_start","generation":1})
            assert ws.receive_json()["type"]=="status"
            ws.send_bytes(frame(seq=2))
            assert ws.receive_json()["type"]=="error"
            ws.send_json({"type":"speech_start","generation":2})
            assert ws.receive_json()["type"]=="status"
            ws.send_json({"type":"interrupt"})
            assert ws.receive_json()["type"]=="interrupted"


def test_tts_invalid_then_retry_or_explicit_failure_no_forged_done():
    class Flaky:
        calls=0
        def synthesize(self,text):
            self.calls+=1
            if self.calls==1:return b"\x00"*4800
            return np.full(2400,330,dtype="<i2").tobytes()
    async def exercise(tts):
        engine=VoiceEngine(Settings(access_key=KEY),ProviderSet(ASR(),LLM(),tts))
        return [e async for e in engine.events(PCM,16000,[],sequence=3)]
    tts=Flaky()
    events=asyncio.run(exercise(tts))
    assert tts.calls==2 and any(e["type"]=="done" for e in events)
    metrics=next(e["data"] for e in events if e["type"]=="metrics")
    assert len(metrics["trace_id"])==16 and metrics["sequence"]==3
    assert metrics["tts_first_phrase_to_pcm_ms"]>=0
    class AlwaysSilent:
        def synthesize(self,text):return b"\x00"*4800
    errors=asyncio.run(exercise(AlwaysSilent()))
    assert any(e["type"]=="error" for e in errors)
    assert not any(e["type"]=="done" for e in errors)


def test_provisional_transcript_is_never_a_tool_write(monkeypatch):
    # Only the final transcript is ever passed to VoiceTools.execute.
    class ProvisionalASR:
        def transcribe(self,wave):return "Create a presentation" if len(wave)<10000 else "Hello"
    class GuardTools:
        store=None
        calls=[]
        async def execute(self,text,*args,**kw):
            self.calls.append(text)
            return None
    async def run():
        tools=GuardTools()
        engine=VoiceEngine(Settings(access_key=KEY),
            ProviderSet(ProvisionalASR(),LLM(),TTS()),tools)
        result=[e async for e in engine.events(PCM,16000,[],owner="owner_test")]
        assert any(e["type"]=="done" for e in result)
        assert tools.calls==["Hello"]
    asyncio.run(run())


def test_duplicate_http_turn_does_not_cancel_the_accepted_turn():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered, release = Event(), Event()

    class SlowASR:
        def transcribe(self, waveform):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test ASR release deadline")
            return "Please explain the result"

    cfg=Settings(access_key=KEY)
    with TestClient(create_app(cfg,ProviderSet(SlowASR(),LLM(),TTS()))) as client:
        headers={"x-rizzler-key":KEY,"x-session-id":"same_owner_http",
                 "x-sample-rate":"16000"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(client.post,"/api/turn",headers=headers,content=PCM)
            try:
                assert entered.wait(4)
                duplicate=client.post("/api/turn",headers=headers,content=PCM)
                assert duplicate.status_code==429
                assert client.app.state.sessions.get("same_owner_http").generation==1
            finally:
                release.set()
            initial=first.result(timeout=8)
            assert initial.status_code==200,initial.text
            assert len(client.app.state.sessions.get("same_owner_http").history)==2


def test_interrupt_queued_http_turn_before_it_can_execute_tools():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered, release = Event(), Event()
    class SlowASR:
        def transcribe(self, waveform):
            entered.set()
            if not release.wait(6):
                raise RuntimeError("Test ASR release deadline")
            return "Please explain the result"
    cfg=Settings(access_key=KEY)
    with TestClient(create_app(cfg,ProviderSet(SlowASR(),LLM(),TTS()))) as client:
        headers=lambda owner:{"x-rizzler-key":KEY,"x-session-id":owner,
                              "x-sample-rate":"16000"}
        with ThreadPoolExecutor(max_workers=3) as pool:
            first=pool.submit(client.post,"/api/turn",
                              headers=headers("holding_owner"),content=PCM)
            try:
                assert entered.wait(4)
                second=pool.submit(client.post,"/api/turn",
                                   headers=headers("queued_owner"),content=PCM)
                import time
                for _ in range(200):
                    if client.app.state.sessions.inference.queued==1:break
                    time.sleep(.01)
                assert client.app.state.sessions.inference.queued==1
                cancelled=client.post("/api/interrupt",headers=headers("queued_owner"))
                assert cancelled.status_code==200 and cancelled.json()["cancelled"] is True
                try:
                    response=second.result(timeout=3)
                except BaseException:
                    # Cancelled ASGI requests may have no HTTP response.
                    response=None
                if response is not None:
                    assert response.status_code!=200
                assert not client.app.state.sessions.get("queued_owner").history
                assert client.app.state.sessions.inference.queued==0
            finally:
                release.set()
            assert first.result(timeout=8).status_code==200
