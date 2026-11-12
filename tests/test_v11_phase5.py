"""V11 Phase 5: real visual parsing/storage/API/voice tests without cloud tokens."""
from __future__ import annotations
import asyncio
import importlib.util
import io
import os
import sqlite3
import tempfile
import unittest

if any(importlib.util.find_spec(x) is None for x in
       ("pytest","fastapi","numpy","httpx","PIL","fitz","cryptography")):
    raise unittest.SkipTest("Visual integration requires app/work/test extras")

import pytest
import fitz
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

from rizzler.media_store import MediaStore, MediaMissing, normalize
from rizzler.visual_intelligence import VisualService, evidence
from rizzler.config import Settings
from rizzler.api import create_app
from rizzler.voice import ProviderSet

KEY="phase5-test-private-access-key-1234567890"
MEDIA_KEY="phase5-independent-visual-encryption-key-123456"
OWNER_A="phase5_alice"
OWNER_B="phase5_bobby"
AUDIO=np.full(16000,1200,dtype="<i2").tobytes()


def jpeg():
    out=io.BytesIO()
    img=Image.new("RGB",(160,100),(83,151,204))
    img.save(out,format="JPEG")
    return out.getvalue()


def png():
    out=io.BytesIO()
    img=Image.new("RGB",(160,100),(25,75,150))
    img.save(out,format="PNG")
    return out.getvalue()


def pdf(pages=2):
    d=fitz.open()
    for i in range(pages):
        page=d.new_page()
        page.insert_text((70,90),f"Page {i+1}: business chart label {i+1}")
        page.draw_rect(fitz.Rect(70,120,230,180))
    result=d.tobytes()
    d.close()
    return result


class Vision:
    def __init__(self):
        self.calls=[]
    async def analyze(self,question,images,context):
        self.calls.append((question,len(images),context))
        return "The screenshot contains a chart. This is user-provided visual evidence."


class ASR:
    def __init__(self):
        self.text="What does this attached image show?"
    def transcribe(self,wave):
        return self.text


class NeverLLM:
    async def stream(self,*a):
        raise AssertionError("Visual requests must never bypass the visual tool")
        yield ""


class TTS:
    def synthesize(self,text):
        return np.full(1200,500,dtype="<i2").tobytes()


def headers(owner):
    return {"x-rizzler-key":KEY,"x-session-id":owner}


def setup(monkeypatch,tmp_path):
    monkeypatch.setenv("RIZZLER_DEPLOYMENT_MODE","demo")
    monkeypatch.setenv("RIZZLER_VISUAL_ENABLED","1")
    monkeypatch.setenv("RIZZLER_VISUAL_KEY",MEDIA_KEY)
    monkeypatch.setenv("RIZZLER_VISUAL_ROOT",str(tmp_path/"visuals"))
    monkeypatch.delenv("RIZZLER_WORK_ROOT",raising=False)
    monkeypatch.delenv("RIZZLER_WORK_SIGNING_KEY",raising=False)
    provider=Vision()
    asr=ASR()
    app=create_app(Settings(access_key=KEY),
                   ProviderSet(asr,NeverLLM(),TTS()))
    app.state.visual.provider=provider
    return app,asr,provider


def test_image_validation_strips_metadata_and_rejects_polyglots():
    mime,data,info=normalize("sample.png",png())
    assert mime=="image/jpeg" and info=={"width":160,"height":100}
    assert data[:2]==b"\xff\xd8"
    assert b"Exif" not in data
    for name,payload in (
        ("unsafe.exe",png()),
        ("sample.jpg",png()),
        ("sample.pdf",png()),
        ("../bad.jpg",jpeg()),
        ("unsafe.svg",b"<svg onload=alert(1)></svg>"),
        ("sample.jpg",b"NOT_AN_IMAGE"*12)):
        with pytest.raises(ValueError):
            normalize(name,payload)


def test_pdf_page_limits_and_actual_pages():
    mime,raw,meta=normalize("report.pdf",pdf(4))
    assert mime=="application/pdf" and meta["pages"]==4
    pictures,context=evidence({"mime":mime,"info":meta},raw)
    assert len(pictures)==3
    assert "first 3 of 4" in context
    assert "Other pages were NOT reviewed" in context
    assert "business chart label" in context
    with pytest.raises(ValueError):
        normalize("too_many.pdf",pdf(25))
    with pytest.raises(ValueError):
        normalize("broken.pdf",b"%PDF-"+b"x"*100)


def test_encrypted_owner_scoped_storage_and_integrity(tmp_path):
    store=MediaStore(tmp_path/"visual",MEDIA_KEY)
    item=store.save(OWNER_A,"test.jpg",jpeg())
    metadata,payload=store.read(OWNER_A,item["id"])
    assert metadata["mime"]=="image/jpeg"
    assert payload[:2]==b"\xff\xd8"
    assert store.save(OWNER_A,"test.jpg",jpeg())["id"]==item["id"]
    with pytest.raises(MediaMissing):
        store.read(OWNER_B,item["id"])
    assert store.delete(OWNER_B,item["id"]) is False
    assert store.read(OWNER_A,item["id"])[0]["id"]==item["id"]
    db=sqlite3.connect(store.path)
    ciphertext=db.execute("SELECT encrypted FROM visuals").fetchone()[0]
    assert ciphertext!=payload and payload not in ciphertext
    db.execute("UPDATE visuals SET encrypted=? WHERE id=?",(b"x"*200,item["id"]))
    db.commit();db.close()
    with pytest.raises(ValueError,match="integrity"):
        store.read(OWNER_A,item["id"])
    assert store.delete(OWNER_A,item["id"])


def test_scanner_unavailable_fails_closed(tmp_path):
    def down(data):
        raise RuntimeError("scanner not ready")
    store=MediaStore(tmp_path/"visual",MEDIA_KEY,scanner=down)
    with pytest.raises(RuntimeError):
        store.save(OWNER_A,"test.jpg",jpeg())
    assert store.list(OWNER_A)==[]


def test_media_quota_prevents_unbounded_files(tmp_path):
    store=MediaStore(tmp_path/"visual",MEDIA_KEY)
    for i in range(6):
        buff=io.BytesIO()
        Image.new("RGB",(100,100),(i*10,9,9)).save(buff,"JPEG")
        store.save(OWNER_A,f"image{i}.jpg",buff.getvalue())
    with pytest.raises(OverflowError):
        store.save(OWNER_A,"other.jpg",jpeg())


def test_visual_service_evidence_is_readonly_and_owner_scoped(tmp_path):
    store=MediaStore(tmp_path/"visual",MEDIA_KEY)
    a=store.save(OWNER_A,"a.jpg",jpeg())["id"]
    b=store.save(OWNER_A,"report.pdf",pdf(2))["id"]
    provider=Vision();service=VisualService(store,provider)
    result=asyncio.run(service.ask(OWNER_A,"Explain the diagrams", [a,b]))
    assert len(result["evidence"])==2
    assert result["pages_inspected"]==3
    assert provider.calls[0][1]==3
    assert "user-provided" in result["answer"]
    with pytest.raises(MediaMissing):
        asyncio.run(service.ask(OWNER_B,"Explain this",[a]))
    with pytest.raises(ValueError):
        asyncio.run(service.ask(OWNER_A,"Explain", [a,a]))
    with pytest.raises(ValueError):
        asyncio.run(service.ask(OWNER_A,"x"*2001,[a]))


def test_authenticated_upload_analysis_deletion_and_voice_handoff(tmp_path,monkeypatch):
    app,asr,provider=setup(monkeypatch,tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/runtime").json()["multimodal_enabled"]
        assert client.post("/api/visual/attachments",headers={"x-file-name":"img.jpg"},
                           content=jpeg()).status_code==401
        upload=client.post("/api/visual/attachments",headers={
            **headers(OWNER_A),"x-file-name":"img.jpg"},content=jpeg())
        assert upload.status_code==201,upload.text
        uid=upload.json()["id"]
        assert client.get("/api/visual/attachments",headers=headers(OWNER_A)
                          ).json()["attachments"][0]["id"]==uid
        assert client.get("/api/visual/attachments",headers=headers(OWNER_B)
                          ).json()["attachments"]==[]
        missing=client.post("/api/visual/ask",headers=headers(OWNER_B),
            json={"question":"What is shown?","attachment_ids":[uid]})
        assert missing.status_code==404,missing.text
        response=client.post("/api/visual/ask",headers=headers(OWNER_A),
            json={"question":"Describe this image","attachment_ids":[uid]})
        assert response.status_code==200,response.text
        assert response.json()["pages_inspected"]==1
        assert provider.calls
        # Finalized voice ASR may analyze a previously shared visual.
        speech=client.post("/api/turn",headers={**headers(OWNER_A),
                            "x-sample-rate":"16000"},content=AUDIO)
        assert speech.status_code==200,speech.text
        assert "screenshot contains a chart" in speech.json()["answer"]
        assert len(provider.calls)==2
        assert client.delete("/api/visual/attachments/"+uid,
                             headers=headers(OWNER_B)).json()["deleted"] is False
        assert client.delete("/api/visual/attachments/"+uid,
                             headers=headers(OWNER_A)).json()["deleted"] is True
        assert client.post("/api/visual/ask",headers=headers(OWNER_A),
            json={"question":"Describe","attachment_ids":[uid]}).status_code==404


def test_provider_failure_does_not_claim_visual_success(tmp_path,monkeypatch):
    app,_,provider=setup(monkeypatch,tmp_path)
    async def fail(*args):
        raise RuntimeError("provider quota / secret provider error")
    provider.analyze=fail
    with TestClient(app) as client:
        uid=client.post("/api/visual/attachments",headers={
            **headers(OWNER_A),"x-file-name":"x.jpg"},content=jpeg()).json()["id"]
        result=client.post("/api/visual/ask",headers=headers(OWNER_A),
             json={"question":"Explain", "attachment_ids":[uid]})
        assert result.status_code==503
        assert "secret provider" not in result.text


def test_media_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("RIZZLER_VISUAL_ENABLED",raising=False)
    monkeypatch.delenv("RIZZLER_WORK_ROOT",raising=False)
    monkeypatch.delenv("RIZZLER_WORK_SIGNING_KEY",raising=False)
    app=create_app(Settings(access_key=KEY),ProviderSet(ASR(),NeverLLM(),TTS()))
    with TestClient(app) as client:
        assert not client.get("/api/runtime").json()["multimodal_enabled"]
        assert client.post("/api/visual/ask",headers=headers(OWNER_A),
            json={"question":"Hello","attachment_ids":["bogus"]}).status_code==409



def test_visual_report_requires_explicit_confirmation_and_durable_work(tmp_path,monkeypatch):
    monkeypatch.setenv("RIZZLER_WORK_ROOT",str(tmp_path/"jobs"))
    monkeypatch.setenv("RIZZLER_WORK_SIGNING_KEY",
                       "independent-test-work-signing-secret-1234567890")
    monkeypatch.setenv("RIZZLER_DEPLOYMENT_MODE","demo")
    monkeypatch.setenv("RIZZLER_VISUAL_ENABLED","1")
    monkeypatch.setenv("RIZZLER_VISUAL_KEY",MEDIA_KEY)
    monkeypatch.setenv("RIZZLER_VISUAL_ROOT",str(tmp_path/"visual"))
    asr=ASR()
    app=create_app(Settings(access_key=KEY),
                   ProviderSet(asr,NeverLLM(),TTS()))
    app.state.visual.provider=Vision()
    from rizzler.work_worker import WorkWorker
    async def report_writer(objective,summary):
        assert "user-supplied visual analysis" in objective
        assert "NOT independently fact-checked" in objective
        return ("# Overview\nThis is a user-provided image description only.\n"
                "## Evidence limits\nNo external citation or visual verification was performed.")
    with TestClient(app) as client:
        uid=client.post("/api/visual/attachments",headers={
            **headers(OWNER_A),"x-file-name":"diagram.png"},content=png()).json()["id"]
        analyzed=client.post("/api/visual/ask",headers=headers(OWNER_A),
            json={"question":"Describe the diagram","attachment_ids":[uid]})
        assert analyzed.status_code==200
        token=analyzed.json()["analysis_id"]
        assert client.get("/api/voice/jobs",headers=headers(OWNER_A)).json()["jobs"]==[]
        for body in (
                {"analysis_id":"wrong","format":"md"},
                {"analysis_id":token,"format":"exe"}):
            assert client.post("/api/visual/report",headers=headers(OWNER_A),
                 json=body).status_code in (400,409)
        assert client.post("/api/visual/report",headers=headers(OWNER_B),
            json={"analysis_id":token,"format":"md"}).status_code==409
        good={"analysis_id":token,"format":"md"}
        first=client.post("/api/visual/report",headers=headers(OWNER_A),json=good)
        assert first.status_code==200,first.text
        repeated=client.post("/api/visual/report",headers=headers(OWNER_A),json=good)
        assert repeated.status_code==200
        jid=first.json()["job"]["id"]
        assert repeated.json()["job"]["id"]==jid
        assert len(app.state.work.list_jobs(OWNER_A))==1
        assert asyncio.run(WorkWorker(app.state.work,composer=report_writer).once())
        assert app.state.work.get(OWNER_A,jid)["status"]=="completed"
        assert app.state.work.quality_report(OWNER_A,jid)["quality"]["passed"]
        artifact=app.state.work.artifacts(OWNER_A,jid)
        assert len(artifact)==1 and artifact[0]["kind"]=="md"
        assert client.get("/api/voice/artifacts/"+artifact[0]["id"],
                          headers=headers(OWNER_B)).status_code==404
        assert client.get("/api/voice/artifacts/"+artifact[0]["id"],
                          headers=headers(OWNER_A)).status_code==200
        # Explicit deletion invalidates new report creation; committed work stays.
        assert client.delete("/api/visual/attachments/"+uid,
                             headers=headers(OWNER_A)).status_code==200
        assert client.post("/api/visual/report",headers=headers(OWNER_A),
            json=good).status_code==409
        assert app.state.work.get(OWNER_A,jid)["status"]=="completed"


def test_provider_timeout_releases_visual_admission(tmp_path):
    store=MediaStore(tmp_path/"visual",MEDIA_KEY)
    uid=store.save(OWNER_A,"image.jpg",jpeg())["id"]
    class Blocking:
        async def analyze(self,question,parts,context):
            raise asyncio.TimeoutError
    visual=VisualService(store,Blocking(),max_active=1)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(visual.ask(OWNER_A,"Explain image",[uid]))
    assert visual._capacity._value==1
