"""Phase 6 runtime load admission tests using a blocked PDF scanner.

No GPU or paid model is required; actual FastAPI upload, worker admission and
protected operational metrics execute with real PDF bytes and storage.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
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
