"""V24 end-to-end control-flow, semantic planning and authorization regressions."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.task_planning import validate_semantic_scope
from rizzler.work_feedback import (
    validate_specialist_feedback, EvidenceGap, ReplanRequired)
from rizzler.work_store import WorkStore
from rizzler.work_specialists import execute_specialists


class ModelOwnedScopeTests(unittest.TestCase):
    def test_semantic_investigation_inferred_without_keyword_routing(self):
        proposal={"research":True,"analysis":False}
        self.assertEqual(validate_semantic_scope(
            proposal,formats=["pptx"],uploads=[],
            forbid_research=False,forbid_analysis=False),proposal)
        with self.assertRaises(PermissionError):
            validate_semantic_scope(proposal,formats=["pptx"],uploads=[],
                                    forbid_research=True,forbid_analysis=False)
        with self.assertRaises(PermissionError):
            validate_semantic_scope({"research":False,"analysis":True},
                                    formats=["pptx"],uploads=[],
                                    forbid_research=False,forbid_analysis=False)
        with self.assertRaises(ValueError):
            validate_semantic_scope({"research":False,"analysis":False},
                                    formats=["pptx","research"],uploads=[],
                                    forbid_research=False,forbid_analysis=False)

    def test_idempotent_user_request_despite_different_source_plan(self):
        with tempfile.TemporaryDirectory() as root:
            store=WorkStore(root)
            first=store.submit(
                "owner", "Research trade balances and build slides",
                ["pptx","research"],"scope-idem-001",[],
                requested_formats=["pptx"])
            duplicate=store.submit(
                "owner", "Research trade balances and build slides",
                ["pptx"],"scope-idem-001",[],
                requested_formats=["pptx"])
            self.assertEqual(first["id"],duplicate["id"])
            with self.assertRaises(ValueError):
                store.submit("owner","Build slides",["pptx","docx"],
                             "scope-idem-002",[],requested_formats=["pptx"])



class NativeIntentDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_infers_required_public_research_for_implicit_task(self):
        from types import SimpleNamespace
        from rizzler.task_planning import propose_semantic_scope
        from rizzler.config import Settings
        try:
            from google.genai import types
        except ImportError:
            self.skipTest("Google GenAI SDK not installed in minimal CI")
        config=Settings(access_key="agent-contract-test-key-12345",
                        gemini_api_key="injected-test-only",
                        gemini_model="fake-model")
        reply=SimpleNamespace(text='{"research":true,"analysis":false}')
        with patch("rizzler.cognitive_provider.generate_with_recovery",
                   new=AsyncMock(return_value=reply)) as model:
            result=await propose_semantic_scope(
                "Prepare a recent global commodity outlook presentation",
                ["pptx"],[],config,client=object())
        self.assertEqual(result["source"],"model_validated")
        self.assertTrue(result["research"])
        self.assertEqual(model.await_count,1)

    async def test_explicit_no_browse_is_not_overrideable_by_model(self):
        from types import SimpleNamespace
        from rizzler.task_planning import propose_semantic_scope
        from rizzler.config import Settings
        try:
            from google.genai import types
        except ImportError:
            self.skipTest("Google GenAI SDK not installed in minimal CI")
        config=Settings(access_key="agent-contract-test-key-12345",
                        gemini_api_key="injected-test-only",
                        gemini_model="fake-model")
        reply=SimpleNamespace(text='{"research":true,"analysis":false}')
        with patch("rizzler.cognitive_provider.generate_with_recovery",
                   new=AsyncMock(return_value=reply)):
            result=await propose_semantic_scope(
                "Create a presentation without research from my supplied notes",
                ["pptx"],[],config,client=object())
        self.assertFalse(result["research"])
        self.assertEqual(result["source"],"explicit_contract_fallback")


class FeedbackRecoveryTests(unittest.TestCase):
    def test_recoverable_gap_never_grants_unplanned_tools(self):
        request={"recipient":"research",
                 "question":"Find the measured rate in official primary sources",
                 "reason":"The rendered chart has no source-backed annual statistic",
                 "blocking":True}
        candidate={"specialist":"powerpoint","readiness":"needs_evidence",
                   "requests":[request],
                   "assessment":"The figure is missing from the actual generated slide."}
        self.assertEqual(validate_specialist_feedback(
            candidate,specialist="powerpoint",permitted=frozenset({"research"})),
            candidate)
        gap=EvidenceGap("powerpoint",[request])
        self.assertEqual(gap.requests,[request])
        with self.assertRaises(ValueError):
            validate_specialist_feedback(candidate,specialist="powerpoint",
                                         permitted=frozenset({"sql_analytics"}))


class BoundedReplanningTests(unittest.IsolatedAsyncioTestCase):
    async def test_replans_only_a_bounded_number_of_times(self):
        expected={"artifacts":3,"complete":True}
        with patch("rizzler.work_specialists._execute_once",
                   new=AsyncMock(side_effect=[
                       ReplanRequired("Updated upstream evidence"),expected])) as work:
            self.assertEqual(await execute_specialists(
                object(),{}, "worker", object(),object()),expected)
            self.assertEqual(work.await_count,2)
        with patch("rizzler.work_specialists._execute_once",
                   new=AsyncMock(side_effect=ReplanRequired("Repeated gap"))) as work:
            with self.assertRaisesRegex(ValueError,"bounded work budget"):
                await execute_specialists(object(),{},"worker",object(),object())
            self.assertEqual(work.await_count,3)




class UserClarificationTests(unittest.TestCase):
    def test_owner_can_resume_same_job_after_answering(self):
        from rizzler.work_store import Conflict, Missing
        with tempfile.TemporaryDirectory() as root:
            store=WorkStore(root)
            job=store.submit("owner1","Explain the trade balance and its period",
                ["md"],"clarification001",[])
            claim=store.claim("worker",lease_seconds=100)
            missing=[{"recipient":"user",
                "question":"Which reporting year should the results cover?",
                "reason":"The report cannot compare trends without a period",
                "blocking":True}]
            store.pause_for_input(claim["id"],"worker",claim["fence"],missing)
            self.assertEqual(store.get("owner1",job["id"])["status"],"awaiting_input")
            questions=store.questions("owner1",job["id"])
            self.assertEqual(len(questions),1)
            with self.assertRaises(Missing):
                store.questions("other_owner",job["id"])
            with self.assertRaises((Missing,Conflict)):
                store.answer_questions("other_owner",job["id"],[
                    {"id":questions[0]["id"],"answer":"2025"}])
            updated=store.answer_questions("owner1",job["id"],[
                {"id":questions[0]["id"],"answer":"Calendar year 2025"}])
            self.assertEqual(updated["status"],"queued")
            self.assertEqual(store.questions(
                "owner1",job["id"])[0]["status"],"answered")
            again=store.claim("worker2",lease_seconds=100)
            self.assertEqual(again["id"],job["id"])

    def test_cancel_awaiting_input_is_terminal(self):
        with tempfile.TemporaryDirectory() as root:
            store=WorkStore(root)
            job=store.submit("owner1","Create a sourced Word report",
                ["docx"],"clarification002",[])
            claim=store.claim("worker",lease_seconds=100)
            store.pause_for_input(claim["id"],"worker",claim["fence"],[
                {"recipient":"user",
                 "question":"What date range should the analysis use?",
                 "reason":"The request has no specified reporting window",
                 "blocking":True}])
            self.assertEqual(store.cancel(
                "owner1",job["id"])["status"],"cancelled")

class WorkerClarificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_does_not_fail_when_user_input_is_needed(self):
        from rizzler.work_worker import WorkWorker
        from rizzler.work_context_intelligence import UserInputRequired
        question={"recipient":"user",
                  "question":"Which currency should the financial results use?",
                  "reason":"The underlying data has no defined display currency",
                  "blocking":True}
        with tempfile.TemporaryDirectory() as root:
            store=WorkStore(root)
            job=store.submit("owner","Create a financial report",
                             ["md"],"clarification003",[])
            with patch("rizzler.work_specialists.execute_specialists",
                 new=AsyncMock(side_effect=UserInputRequired([question]))):
                self.assertTrue(await WorkWorker(store).once())
            self.assertEqual(store.get("owner",job["id"])["status"],
                             "awaiting_input")
            self.assertEqual(len(store.questions("owner",job["id"])),1)

if __name__=="__main__":
    unittest.main()
