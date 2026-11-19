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


if __name__=="__main__":
    unittest.main()
