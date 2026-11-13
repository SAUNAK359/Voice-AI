"""Phase 6 runtime load admission tests using a blocked PDF scanner.

No GPU or paid model is required; actual FastAPI upload, worker admission and
protected operational metrics execute with real PDF bytes and storage.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

CAPABLE=all(importlib.util.find_spec(x) is not None for x in
            ("fastapi","httpx","fitz","numpy","cryptography","PIL"))


@unittest.skipUnless(CAPABLE,"Phase 6 runtime tests require application extras")
class Phase6RuntimeTests(unittest.TestCase):
    def test_pdf_admission_is_bounded_with_persistent_queue(self):
        import fitz
        import numpy as np
        from fastapi.testclient import TestClient
        from rizzler.api import create_app
        from rizzler.config import Settings
        from rizzler.voice import ProviderSet
        from rizzler.production_guard import budget_from_environment
        class ASR:
            def transcribe(self,data):return "Test"
        class LLM:
            async def stream(self,*args):
                yield "Test response"
        class TTS:
            def synthesize(self,text):
                return np.ones(2400,dtype="<i2").tobytes()
        class Vision:
            async def analyze(self,*args):
                return "The illustrated PDF page has a visible header."
        def raw_pdf():
            d=fitz.open()
            d.new_page(width=500,height=620).insert_text((50,50),"Full page")
            data=d.tobytes()
            d.close()
            return data
        raw=raw_pdf()
        access="v11-phase6-verified-demo-key"
        operation_token="independent-v11-phase6-operations-test-token"
        arrived=threading.Event()
        resume=threading.Event()
        def slow_scan(path):
            arrived.set()
            if not resume.wait(timeout=8):
                raise RuntimeError("Intentional scanner test deadline exceeded")
        with __import__("tempfile").TemporaryDirectory() as tmp:
            env={
                "RIZZLER_DEPLOYMENT_MODE":"demo",
                "RIZZLER_VISUAL_ENABLED":"1",
                "RIZZLER_VISUAL_ROOT":str(Path(tmp)/"visual"),
                "RIZZLER_VISUAL_KEY":"phase6-independent-test-visual-key-123456",
                "RIZZLER_PDF_MAX_ACTIVE":"1",
                "RIZZLER_OPERATIONS_TOKEN":operation_token,
            }
            with patch.dict(os.environ,env,clear=True):
                budget_from_environment.cache_clear()
                app=create_app(Settings(access_key=access),
                               ProviderSet(ASR(),LLM(),TTS()))
                app.state.pdf_store.scanner_file=slow_scan
                app.state.pdf_ingestor.provider=Vision()
                headers={"x-rizzler-key":access,"x-session-id":"phase6_owner"}
                with TestClient(app) as client:
                    documents=[]
                    for index in range(2):
                        created=client.post("/api/pdf/documents",headers=headers,
                           json={"name":f"large_{index}.pdf","bytes":len(raw)})
                        self.assertEqual(created.status_code,201,created.text)
                        uid=created.json()["id"]
                        result=client.put(f"/api/pdf/documents/{uid}/chunks/0",
                            headers={**headers,
                              "x-chunk-sha256":hashlib.sha256(raw).hexdigest()},
                            content=raw)
                        self.assertEqual(result.status_code,200,result.text)
                        documents.append(uid)
                    try:
                        started=client.post(
                            f"/api/pdf/documents/{documents[0]}/complete",headers=headers)
                        self.assertEqual(started.status_code,202,started.text)
                        self.assertTrue(arrived.wait(5))
                        second=client.post(
                            f"/api/pdf/documents/{documents[1]}/complete",headers=headers)
                        self.assertEqual(second.status_code,202,second.text)
                        metrics=client.get("/internal/metrics",headers={
                            "authorization":"Bearer "+operation_token})
                        self.assertEqual(metrics.status_code,200,metrics.text)
                        self.assertEqual(metrics.json()["pdf_scheduler"]["limit"],1)
                        self.assertEqual(metrics.json()["pdf_scheduler"]["active"],1)
                        pending=client.get(
                            f"/api/pdf/documents/{documents[1]}",headers=headers)
                        self.assertEqual(pending.status_code,200)
                        self.assertEqual(pending.json()["status"],"validating")
                    finally:
                        resume.set()
                budget_from_environment.cache_clear()

    def test_paused_pdf_and_research_resume_are_persistently_queued(self):
        import tempfile
        import secrets
        from rizzler.pdf_documents import PDFStore
        from rizzler.pdf_analysis import PDFResearch
        with tempfile.TemporaryDirectory() as tmp:
            owner="phase6_owner"
            store=PDFStore(Path(tmp)/"pdfs",
                           "phase6-independent-doc-encryption-secret-123456")
            doc=store.create(owner,"manual.pdf")
            with store.db() as db:
                db.execute("UPDATE docs SET status='paused' WHERE id=?",(doc["id"],))
            resumed=store.request_resume(owner,doc["id"])
            self.assertEqual(resumed["status"],"queued")
            self.assertIn((owner,doc["id"]),store.recoverable())
            class Vision:pass
            research=PDFResearch(store,Vision())
            run=secrets.token_urlsafe(24)
            now=time.time()
            with store.db() as db:
                db.execute("""INSERT INTO pdf_answers
                  (id,owner,doc,question,mode,status,total_pages,created,updated)
                  VALUES(?,?,?,?,?,?,?,?,?)""",
                   (run,owner,doc["id"],"Summarize all","full","paused",2,now,now))
            record=research.request_resume(owner,run)
            self.assertEqual(record["status"],"queued")
            self.assertIn((owner,run),research.recoverable())

    def test_planning_correction_and_live_search_obey_shared_budget(self):
        import asyncio
        from types import SimpleNamespace
        from rizzler.config import Settings
        from rizzler.task_planning import propose_scope
        from rizzler.voice_tools import grounded_search
        from rizzler.production_guard import budget_from_environment
        from google import genai
        class Models:
            def __init__(self):
                self.calls=0
            async def generate_content(self,**kwargs):
                self.calls+=1
                return SimpleNamespace(text='{"research":true,"analysis":false}')
        class AIO:
            def __init__(self,models):self.models=models
            async def aclose(self):pass
        with __import__("tempfile").TemporaryDirectory() as tmp:
            env={
                "RIZZLER_AI_DAILY_BUDGET_USD":"0.10",
                "RIZZLER_AI_RESERVATION_PER_CALL_USD":"0.10",
                "RIZZLER_AI_BUDGET_ROOT":tmp,
            }
            with patch.dict(os.environ,env,clear=True):
                budget_from_environment.cache_clear()
                models=Models()
                client=SimpleNamespace(aio=AIO(models))
                cfg=Settings(access_key="private-phase6-budget-client-access-key",
                             gemini_api_key="mock-key")
                good=asyncio.run(propose_scope(
                    "Research up-to-date sources for a report",
                    ["pdf","md"],[],cfg,client=client))
                self.assertEqual(good["source"],"model_validated")
                self.assertEqual(models.calls,1)
                denied=asyncio.run(propose_scope(
                    "Research up-to-date sources for a report",
                    ["pdf","md"],[],cfg,client=client))
                self.assertEqual(denied["source"],"deterministic_fallback")
                self.assertEqual(models.calls,1)
                with patch.object(genai,"Client",return_value=client):
                    search=asyncio.run(grounded_search("Search web for current news",cfg))
                self.assertFalse(search["verified"])
                self.assertEqual(models.calls,1)
                self.assertEqual(
                    sum(budget_from_environment().snapshot()["requests"].values()),1)
                budget_from_environment.cache_clear()

    def test_invalid_pdf_parallel_limit_is_rejected_on_startup(self):
        from rizzler.api import create_app
        from rizzler.config import Settings
        from rizzler.voice import ProviderSet
        class Mock:pass
        with patch.dict(os.environ,{
            "RIZZLER_DEPLOYMENT_MODE":"demo",
            "RIZZLER_PDF_MAX_ACTIVE":"0",
        },clear=True):
            with self.assertRaises(ValueError):
                create_app(Settings(access_key="phase6-limit-contract-private-key"),
                           ProviderSet(Mock(),Mock(),Mock()))


if __name__=="__main__":
    unittest.main()
