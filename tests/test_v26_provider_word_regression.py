"""Regression gates for V26 exact Kaggle failures: Word Settings and Gemini status."""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rizzler.work_diagnostics import failure_code, failure_record, provider_http_status
from rizzler.cognitive_provider import _transient

ROOT=Path(__file__).resolve().parents[1]


class WordSettingsTests(unittest.TestCase):
    def test_word_pdf_planner_initializes_its_own_settings(self):
        program=ast.parse((ROOT/"src/rizzler/work_specialists.py").read_text())
        defs=[node for node in ast.walk(program) if isinstance(node,ast.AsyncFunctionDef)
              and node.name=="build_format_plan"]
        self.assertEqual(len(defs),1)
        planner=defs[0]
        imports=[node for node in planner.body if isinstance(node,ast.ImportFrom)
                 and node.module=="config" and any(a.name=="Settings" for a in node.names)]
        self.assertEqual(len(imports),1,
             "Settings must not depend on Excel or PowerPoint branch initialization")
        report_calls=[node for node in ast.walk(planner)
                      if isinstance(node,ast.Call) and
                      isinstance(node.func,ast.Attribute) and
                      node.func.attr=="from_env"]
        self.assertTrue(report_calls)


class ProviderStatusTests(unittest.TestCase):
    def test_numeric_response_status_is_safe_and_classified(self):
        for status,code,transient in [
                (400,"provider_invalid_request",False),
                (401,"provider_authorization",False),
                (403,"provider_authorization",False),
                (429,"provider_transient",True),
                (503,"provider_transient",True)]:
            with self.subTest(status=status):
                error=type("SafeProviderError",(Exception,),{
                    "response":type("Response",(),{"status_code":status})()})(
                    "PRIVATE API PROMPT MUST NOT APPEAR")
                self.assertEqual(provider_http_status(error),status)
                self.assertEqual(failure_code(error),code)
                self.assertEqual(_transient(error),transient)
                record=failure_record(error,"powerpoint")
                self.assertEqual(record["http_status"],status)
                self.assertNotIn("PRIVATE",str(record))
                self.assertNotIn("PROMPT",str(record))
                self.assertNotIn("response",record)
    def test_http_diagnostics_survive_actual_fenced_workstore_persistence(self):
        from tempfile import TemporaryDirectory
        from rizzler.work_store import WorkStore
        with TemporaryDirectory() as temp:
            owner="v26_provider_owner"
            store=WorkStore(temp)
            job=store.submit(owner,"Produce a professional source-grounded report",
                             ["pptx"],"v26_status_0001",[])
            claim=store.claim("v26_worker")
            self.assertEqual(claim["id"],job["id"])
            error=type("ProviderClientError",(Exception,),{
                "response":type("Response",(),{"status_code":400})()})(
                "PRIVATE PROVIDER ERROR BODY")
            diagnosis=failure_record(error,"powerpoint")
            store.agent_error(claim["id"],"v26_worker",claim["fence"],
                              "powerpoint",code=failure_code(error),
                              diagnosis=diagnosis)
            observations=store.diagnostics(owner,claim["id"])
            self.assertEqual(len(observations),1)
            self.assertEqual(observations[0]["http_status"],400)
            self.assertEqual(observations[0]["code"],"provider_invalid_request")
            self.assertNotIn("PRIVATE",str(observations))
            # The persistent schema rejects free-form provider messages.
            bad=dict(diagnosis)
            bad["provider_message"]="PRIVATE SENSITIVE CONTENT"
            with store._tx() as tx, self.assertRaises(ValueError):
                store._diagnostic(tx,claim["id"],owner,bad)
            wrong=dict(diagnosis)
            wrong["http_status"]=503
            with store._tx() as tx, self.assertRaises(ValueError):
                store._diagnostic(tx,claim["id"],owner,wrong)

    def test_non_numeric_fields_do_not_leak_or_bypass_retry_policy(self):
        error=type("ClientError",(Exception,),{"code":"SECRET HTTP 503 with PII"})(
            "Private contents")
        self.assertIsNone(provider_http_status(error))
        self.assertNotIn("SECRET",str(failure_record(error,"orchestrator")))
