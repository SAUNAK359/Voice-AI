"""V11 Phase 6 shared owner admission: atomic quotas and API authorization.

All tests are offline. A local SQLite filesystem is not a globally
distributed WAF or an actual Gemini billing control.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from rizzler.owner_admission import OwnerRateLedger, RateExceeded, classify


class SharedAdmissionTests(unittest.TestCase):
    KEY="independent-v11-admission-signature-key-1234567890"

    def test_atomic_multi_instance_owner_and_class_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"limits.sqlite3"
            settings={"standard":8,"expensive":3,"upload":20,"work":4,"connect":2}
            ledgers=[OwnerRateLedger(path,self.KEY,settings) for _ in range(4)]
            def attempt(index):
                try:
                    ledgers[index%len(ledgers)].admit("authenticated-owner","expensive",at=120.5)
                    return True
                except RateExceeded as exc:
                    self.assertEqual(exc.retry_after,60)
                    return False
            with ThreadPoolExecutor(max_workers=12) as pool:
                results=list(pool.map(attempt,range(40)))
            self.assertEqual(sum(results),3)
            self.assertEqual(ledgers[0].admit("another-owner","expensive",at=120.5),2)
            self.assertEqual(ledgers[0].admit("authenticated-owner","standard",at=120.5),7)
            self.assertEqual(ledgers[-1].admit("authenticated-owner","expensive",at=180.5),2)
            with sqlite3.connect(path) as db:
                sample=db.execute("SELECT subject FROM rates LIMIT 1").fetchone()[0]
                self.assertEqual(len(sample),32)
                self.assertNotIn(b"authenticated-owner",sample)
                self.assertNotIn(b"another-owner",sample)

    def test_reject_bad_owner_configuration_and_rate_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"admission.sqlite3"
            for invalid in ("relative.sqlite3",):
                with self.assertRaises(ValueError):
                    OwnerRateLedger(invalid,self.KEY)
            with self.assertRaises(ValueError):
                OwnerRateLedger(path,"short")
            with self.assertRaises(ValueError):
                OwnerRateLedger(path,self.KEY,{"standard":5})
            db=OwnerRateLedger(path,self.KEY)
            for owner in ("",None):
                with self.assertRaises(ValueError):
                    db.admit(owner,"standard")
            with self.assertRaises(ValueError):
                db.admit("valid-owner","arbitrary-model-category")
            with self.assertRaises(ValueError):
                db.admit("valid-owner","standard",at=float("nan"))

    def test_routes_classified_without_storing_private_file_names(self):
        expected={
            ("POST","/api/turn"):"expensive",
            ("POST","/api/visual/ask"):"expensive",
            ("POST","/api/pdf/documents/secret_doc/research"):"expensive",
            ("POST","/api/pdf/research/secret_run/resume"):"expensive",
            ("PUT","/api/pdf/documents/secret_doc/chunks/999999"):"upload",
            ("POST","/api/work/jobs"):"work",
            ("GET","/api/work/jobs/id"):"standard",
            ("GET","/api/pdf/documents/id"):"standard",
            ("WS","/ws"):"connect",
        }
        for (verb,url),kind in expected.items():
            self.assertEqual(classify(verb,url),kind)
        with tempfile.TemporaryDirectory() as tmp:
            db=OwnerRateLedger(Path(tmp)/"admission.sqlite3",self.KEY)
            db.admit("private_owner",classify("PUT","/api/pdf/documents/secret/chunks/5"))
            raw=Path(tmp,"admission.sqlite3").read_bytes()
            self.assertNotIn(b"secret",raw)
            self.assertNotIn(b"private_owner",raw)

    def test_rollover_and_operator_summary_do_not_expose_subjects(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=OwnerRateLedger(Path(tmp)/"admission.sqlite3",self.KEY)
            db.admit("owner-abc","standard")
            report=db.snapshot()
            self.assertIn("requests_by_class",report)
            self.assertNotIn("owner-abc",str(report))
            self.assertEqual(report["requests_by_class"].get("standard"),1)
            self.assertEqual(report["window_seconds"],60)


@unittest.skipUnless(all(importlib.util.find_spec(m) is not None for m in
    ("fastapi","httpx","numpy","cryptography")),
    "API admission tests require app/test extras")
class AdmissionIntegrationTests(unittest.TestCase):
    KEY="demo-independently-issued-access-key"
    ADMISSION="independent-admission-test-key-1234567890"

    def _app(self):
        from rizzler.api import create_app
        from rizzler.config import Settings
        from rizzler.voice import ProviderSet
        class ASR:
            def transcribe(self,wave):
                return "Hello"
        class LLM:
            async def stream(self,text,history):
                yield "Hello, can I help?"
        class TTS:
            def synthesize(self,text):
                import numpy as np
                return np.full(1200,280,dtype="<i2").tobytes()
        return create_app(Settings(access_key=self.KEY),
                          ProviderSet(ASR(),LLM(),TTS()))

    def test_demo_auth_rejects_first_then_limits_owner_without_affecting_other(self):
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as tmp:
            env={
                "RIZZLER_DEPLOYMENT_MODE":"demo",
                "RIZZLER_ADMISSION_ENABLED":"1",
                "RIZZLER_ADMISSION_SECRET":self.ADMISSION,
                "RIZZLER_ADMISSION_ROOT":tmp,
                "RIZZLER_RATE_STANDARD_PER_MIN":"2",
            }
            with patch.dict(os.environ,env,clear=True):
                with TestClient(self._app()) as client:
                    wrong={"x-rizzler-key":"wrong","x-session-id":"owner_demo_1"}
                    self.assertEqual(client.get("/api/voice/admission",headers=wrong).status_code,401)
                    ok={"x-rizzler-key":self.KEY,"x-session-id":"owner_demo_1"}
                    for _ in range(2):
                        self.assertEqual(client.get("/api/voice/admission",headers=ok).status_code,200)
                    throttled=client.get("/api/voice/admission",headers=ok)
                    self.assertEqual(throttled.status_code,429)
                    self.assertTrue(throttled.headers.get("retry-after","").isdigit())
                    other={"x-rizzler-key":self.KEY,"x-session-id":"owner_demo_2"}
                    self.assertEqual(client.get("/api/voice/admission",headers=other).status_code,200)
                    metrics=client.get("/internal/metrics")
                    self.assertEqual(metrics.status_code,401)
                    self.assertIsNotNone(client.app.state.owner_admission)

    def test_voice_and_work_use_same_owner_admission_and_no_second_bearer(self):
        from fastapi.testclient import TestClient
        from rizzler.work_auth import issue_token
        with tempfile.TemporaryDirectory() as tmp:
            env={
                "RIZZLER_DEPLOYMENT_MODE":"demo",
                "RIZZLER_WORK_ROOT":str(Path(tmp)/"work"),
                "RIZZLER_ADMISSION_ENABLED":"1",
                "RIZZLER_ADMISSION_SECRET":self.ADMISSION,
                "RIZZLER_ADMISSION_ROOT":str(Path(tmp)/"work"),
                "RIZZLER_RATE_STANDARD_PER_MIN":"1",
            }
            with patch.dict(os.environ,env,clear=True):
                with TestClient(self._app()) as client:
                    missing={"x-rizzler-key":self.KEY}
                    self.assertEqual(client.get("/api/work/skills",headers=missing).status_code,400)
                    owner={"x-rizzler-key":self.KEY,"x-session-id":"account_one"}
                    self.assertEqual(client.get("/api/work/skills",headers=owner).status_code,200)
                    self.assertEqual(client.get("/api/voice/jobs",headers=owner).status_code,429)
                    other={"x-rizzler-key":self.KEY,"x-session-id":"account_two"}
                    self.assertEqual(client.get("/api/work/skills",headers=other).status_code,200)
                    legacy=issue_token("account_three","independent-signing-secret-1234567890")
                    self.assertEqual(client.get("/api/work/skills",headers={
                        "authorization":"Bearer "+legacy}).status_code,401)

    def test_websocket_owner_connect_has_independent_limit(self):
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect
        with tempfile.TemporaryDirectory() as tmp:
            env={
                "RIZZLER_DEPLOYMENT_MODE":"demo",
                "RIZZLER_ADMISSION_ENABLED":"1",
                "RIZZLER_ADMISSION_SECRET":self.ADMISSION,
                "RIZZLER_ADMISSION_ROOT":tmp,
                "RIZZLER_RATE_CONNECT_PER_MIN":"1",
            }
            with patch.dict(os.environ,env,clear=True):
                with TestClient(self._app()) as client:
                    data={"type":"auth","token":self.KEY,"client_id":"account_voice",
                          "sample_rate":16000,"protocol":2}
                    with client.websocket_connect("/ws",
                         headers={"origin":"http://testserver"}) as socket:
                        socket.send_json(data)
                        self.assertEqual(socket.receive_json()["type"],"ready")
                    with self.assertRaises(WebSocketDisconnect) as caught:
                        with client.websocket_connect("/ws",
                            headers={"origin":"http://testserver"}) as socket:
                            socket.send_json(data)
                            socket.receive_json()
                    self.assertEqual(caught.exception.code,1013)

    def test_invalid_admission_configuration_fails_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ,{
                "RIZZLER_DEPLOYMENT_MODE":"demo",
                "RIZZLER_ADMISSION_ENABLED":"1",
                "RIZZLER_ADMISSION_SECRET":self.KEY,
                "RIZZLER_ADMISSION_ROOT":tmp,
                "RIZZLER_RATE_STANDARD_PER_MIN":"0",
            },clear=True):
                with self.assertRaises(ValueError):
                    self._app()


if __name__=="__main__":
    unittest.main()
