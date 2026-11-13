"""Full-document PDF regression: no product-level page cap, complete coverage,
encrypted chunks, resumable visual tiles, all-page research and authenticated API.
The Gemini provider is the only test double.
"""
from __future__ import annotations

import asyncio
import importlib.util
import hashlib
import time
import unittest

if any(importlib.util.find_spec(x) is None for x in
       ("pytest","fitz","fastapi","httpx","cryptography","numpy")):
    raise unittest.SkipTest("Full PDF integration requires app/test/work extras")

import fitz
import numpy as np
import pytest
from fastapi.testclient import TestClient

from rizzler.pdf_documents import (PDFStore,PDFIngestor,DocumentConflict,
                                    DocumentNotFound,rectangles,CHUNK_BYTES)
from rizzler.pdf_analysis import PDFResearch
from rizzler.api import create_app
from rizzler.config import Settings
from rizzler.voice import ProviderSet

OWNER="pdf_v11_main_owner"
OTHER="pdf_v11_other_owner"
ACCESS_KEY="independent-v11-pdf-test-access-key"
SECRET="pdf-encryption-key-for-integration-tests-0123456789"


def make_pdf(n):
    pdf=fitz.open()
    for i in range(n):
        page=pdf.new_page(width=500,height=650)
        page.insert_text((50,60),f"PAGE {i+1} FACT ledger row {i+1}")
        page.draw_rect(fitz.Rect(45,100,120,160))
    result=pdf.tobytes()
    pdf.close()
    return result


class MockVision:
    def __init__(self):
        self.calls=[]
    async def analyze(self,question,images,context):
        self.calls.append((question,len(images),context[:150]))
        if images:
            return "Verified raster received for a PDF visual tile; label and diagram visible."
        return "Model synthesis based solely on the supplied page citations and indexed text."


class ASR:
    def transcribe(self,wave):
        return "How can I analyze my PDF?"


class LLM:
    async def stream(self,text,history):
        yield "Your uploaded PDF is indexed asynchronously."


class TTS:
    def synthesize(self,text):
        return np.full(2400,250,dtype="<i2").tobytes()


def _upload(store,payload,owner=OWNER):
    created=store.create(owner,"whole_manual.pdf")
    uid=created["id"]
    for i in range(0,len(payload),CHUNK_BYTES):
        chunk=payload[i:i+CHUNK_BYTES]
        store.append(owner,uid,i//CHUNK_BYTES,chunk,hashlib.sha256(chunk).hexdigest())
    return uid


def test_126_page_ingestion_has_no_preview_or_page_cap(tmp_path):
    store=PDFStore(tmp_path/"pdfs",SECRET)
    uid=_upload(store,make_pdf(126))
    assert store.finalize(OWNER,uid)["pages"]==126
    model=MockVision()
    report=asyncio.run(PDFIngestor(store,model).run(OWNER,uid))
    assert report["status"]=="complete" and report["processed_pages"]==126
    assert len([c for c in model.calls if c[1]])==126
    assert store.read_page(OWNER,uid,125)["page"]==126
    assert "PAGE 126" in store.read_page(OWNER,uid,125)["text"]
    assert len(store.page_numbers(OWNER,uid))==126
    assert 125 in store.search_pages(OWNER,uid,"PAGE 126 ledger")
    assert "page" in store.read_page(OWNER,uid,80)


def test_checkpoint_resume_after_forced_cancel_and_restart(tmp_path):
    store=PDFStore(tmp_path/"pdfs",SECRET)
    uid=_upload(store,make_pdf(9))
    store.finalize(OWNER,uid)
    class CancelAtThirdTile(MockVision):
        async def analyze(self,question,images,context):
            if len(self.calls)==3:raise asyncio.CancelledError()
            return await super().analyze(question,images,context)
    flawed=CancelAtThirdTile()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(PDFIngestor(store,flawed).run(OWNER,uid))
    partial=store.status(OWNER,uid)
    assert partial["status"]=="paused"
    assert partial["processed_pages"]==3
    # Different object, same encrypted store; no completed page is rerendered.
    recovered=PDFStore(tmp_path/"pdfs",SECRET)
    succeeding=MockVision()
    result=asyncio.run(PDFIngestor(recovered,succeeding).run(OWNER,uid))
    assert result["processed_pages"]==9 and result["status"]=="complete"
    assert len(succeeding.calls)==6
    assert len(recovered.pages(OWNER,uid))==9


def test_encrypted_chunks_replay_authorization_deletion_and_tamper(tmp_path):
    store=PDFStore(tmp_path/"pdfs",SECRET)
    uid=_upload(store,make_pdf(2))
    with pytest.raises(DocumentNotFound):
        store.status(OTHER,uid)
    assert store.list(OTHER)==[]
    with pytest.raises(DocumentNotFound):
        store.delete(OTHER,uid)
    with store.db() as db:
        row=db.execute("SELECT encrypted FROM chunks WHERE doc=?",(uid,)).fetchone()
        assert b"%PDF-" not in row["encrypted"]
        db.execute("UPDATE chunks SET encrypted=? WHERE doc=?", (b"X"*128,uid))
    with pytest.raises(ValueError,match="authentication"):
        store.finalize(OWNER,uid)
    removed=store.delete(OWNER,uid)
    assert removed


def test_mismatched_chunk_replay_never_rewrites_bytes(tmp_path):
    store=PDFStore(tmp_path/"pdfs",SECRET)
    uid=store.create(OWNER,"test.pdf")["id"]
    packet=b"%PDF-"+b"x"*1024
    digest=hashlib.sha256(packet).hexdigest()
    store.append(OWNER,uid,0,packet,digest)
    same=store.append(OWNER,uid,0,packet,digest)
    assert same["uploaded_chunks"]==1
    with pytest.raises(DocumentConflict):
        data=packet+b"different"
        store.append(OWNER,uid,0,data,hashlib.sha256(data).hexdigest())
    with pytest.raises(DocumentConflict):
        store.append(OWNER,uid,2,packet,digest)
    with pytest.raises(ValueError):
        store.append(OWNER,uid,1,packet,"0"*64)


def test_complete_document_research_accounts_for_every_page(tmp_path):
    store=PDFStore(tmp_path/"pdfs",SECRET)
    uid=_upload(store,make_pdf(36))
    store.finalize(OWNER,uid)
    vision=MockVision()
    asyncio.run(PDFIngestor(store,vision).run(OWNER,uid))
    engine=PDFResearch(store,vision)
    research=engine.submit(OWNER,uid,"Explain every ledger row",mode="full")
    result=asyncio.run(engine.run(OWNER,research["id"]))
    assert result["status"]=="complete"
    assert result["total_pages"]==result["covered_pages"]==36
    assert result["coverage"]=="all_pages"
    assert result["completed_units"]>36
    assert "Model synthesis" in result["answer"]
    with pytest.raises(DocumentNotFound):
        engine.status(OTHER,research["id"])
    assert store.delete(OWNER,uid)
    with pytest.raises(DocumentNotFound):
        engine.status(OWNER,research["id"])


def test_tile_generator_covers_large_pages_without_allocating_giant_bitmap():
    import fitz
    bounds=fitz.Rect(0,0,18000,18000)
    boxes=list(rectangles(bounds))
    assert len(boxes)>500
    assert boxes[0][1].x0==0 and boxes[-1][1].x1==18000
    assert boxes[-1][1].y1==18000
    assert max(b.width*b.height for _,b in boxes)<=720*720


def test_api_complete_upload_status_and_full_question(tmp_path,monkeypatch):
    monkeypatch.setenv("RIZZLER_DEPLOYMENT_MODE","demo")
    monkeypatch.setenv("RIZZLER_VISUAL_ENABLED","1")
    monkeypatch.setenv("RIZZLER_VISUAL_ROOT",str(tmp_path/"visual"))
    monkeypatch.setenv("RIZZLER_VISUAL_KEY",SECRET)
    monkeypatch.delenv("RIZZLER_WORK_ROOT",raising=False)
    monkeypatch.delenv("RIZZLER_WORK_SIGNING_KEY",raising=False)
    app=create_app(Settings(access_key=ACCESS_KEY),
        ProviderSet(ASR(),LLM(),TTS()))
    vision=MockVision()
    app.state.pdf_ingestor.provider=vision
    app.state.pdf_research.provider=vision
    hdr={"x-rizzler-key":ACCESS_KEY,"x-session-id":OWNER}
    raw=make_pdf(27)
    with TestClient(app) as client:
        doc=client.post("/api/pdf/documents",headers=hdr,json={
            "name":"any_length.pdf","bytes":len(raw)})
        assert doc.status_code==201,doc.text
        uid=doc.json()["id"]
        assert client.get("/api/pdf/documents/"+uid,headers={
            **hdr,"x-session-id":OTHER}).status_code==404
        for n,start in enumerate(range(0,len(raw),1024)):
            part=raw[start:start+1024]
            uploaded=client.put(f"/api/pdf/documents/{uid}/chunks/{n}",
                headers={**hdr,"x-chunk-sha256":hashlib.sha256(part).hexdigest()},
                content=part)
            assert uploaded.status_code==200,uploaded.text
        completed=client.post(f"/api/pdf/documents/{uid}/complete",headers=hdr)
        assert completed.status_code==202,completed.text
        limit=time.monotonic()+15
        while time.monotonic()<limit:
            snapshot=client.get("/api/pdf/documents/"+uid,headers=hdr).json()
            if snapshot["status"] in ("complete","paused"):break
            time.sleep(.08)
        assert snapshot["status"]=="complete",snapshot
        assert snapshot["processed_pages"]==27
        start=client.post(f"/api/pdf/documents/{uid}/research",headers=hdr,
            json={"question":"Analyze every page of this manual","mode":"full"})
        assert start.status_code==202,start.text
        run_id=start.json()["id"]
        limit=time.monotonic()+15
        while time.monotonic()<limit:
            result=client.get("/api/pdf/research/"+run_id,headers=hdr).json()
            if result["status"] in ("complete","paused"):break
            time.sleep(.08)
        assert result["status"]=="complete",result
        assert result["total_pages"]==result["covered_pages"]==27
        assert client.get("/api/pdf/research/"+run_id,headers={
            **hdr,"x-session-id":OTHER}).status_code==404
        deleted=client.delete("/api/pdf/documents/"+uid,headers=hdr)
        assert deleted.status_code==200,deleted.text
        assert client.get("/api/pdf/documents/"+uid,headers=hdr).status_code==404
