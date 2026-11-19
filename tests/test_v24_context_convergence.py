"""V24 non-destructive repair, contextual requirements and backdelegation tests."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rizzler.work_context_intelligence import (
    validate_context_review, snapshot_context, context_brief,
    converge_context, _merge_validated)
from rizzler.work_ir import compile_ir
from rizzler.work_repair import (
    storyboard_diagnostics, apply_storyboard_patch)
from rizzler.work_studio import validate_storyboard


class TargetedStoryboardSafetyTests(unittest.TestCase):
    def setUp(self):
        self.ir = compile_ir(
            "Export analysis",
            "# Objective\nThe source reports a historical 2025 value of 125 units.\n"
            "## Method\nComparisons must preserve the measurement period.\n"
            "## Action\nRecommendations require verified source evidence.",
            ["https://example.org/report"])
        self.original = {"schema_version": 1, "slides": [
            {"title": "2025", "message": "The analysis measures 125 units",
             "kind": "takeaway", "bullets": [
                 "The verified value is 125 units in 2025.",
                 "All comparisons must use matching periods."],
             "section_ids": [0], "source_urls": ["https://example.org/report"]},
            {"title": "Verified evidence", "message": "Source citations matter for accuracy",
             "kind": "evidence", "bullets": [
                 "The source covers the measurement period.",
                 "Data must be reconciled before publication."],
             "section_ids": [1], "source_urls": ["https://example.org/report"]},
            {"title": "Next steps for reviewers", "message": "Confirm evidence before action",
             "kind": "decision", "bullets": [
                 "Check methods and measurement limitations.",
                 "Maintain an auditable evidence trail."],
             "section_ids": [2], "source_urls": []},
        ]}

    def test_valid_repair_only_changes_target_field(self):
        before = deepcopy(self.original)
        diagnostics = storyboard_diagnostics(before)
        self.assertEqual([(x["index"], x["field"]) for x in diagnostics], [(0,"title")])
        repaired = apply_storyboard_patch(before, {"changes": [
            {"index": 0, "field": "title", "replacement": "Trade outlook for 2025"}]},
            diagnostics=diagnostics)
        self.assertEqual(repaired["slides"][1:], before["slides"][1:])
        self.assertEqual(repaired["slides"][0]["section_ids"],
                         before["slides"][0]["section_ids"])
        self.assertEqual(repaired["slides"][0]["bullets"],
                         before["slides"][0]["bullets"])
        self.assertEqual(before["slides"][0]["title"], "2025")
        validated = validate_storyboard(
            repaired, self.ir.sections, self.ir.sources)
        self.assertEqual(validated["sections_covered"], [0,1,2])

    def test_repair_cannot_erase_numbers_or_modify_sources(self):
        d = storyboard_diagnostics(self.original)
        with self.assertRaisesRegex(ValueError, "numerical"):
            apply_storyboard_patch(self.original, {"changes": [
                {"index":0, "field":"title",
                 "replacement":"Trade outlook for 2026"}]}, diagnostics=d)
        with self.assertRaisesRegex(ValueError, "protected"):
            apply_storyboard_patch(self.original, {"changes": [
                {"index":0, "field":"source_urls",
                 "replacement":"https://bogus.invalid"}]}, diagnostics=d)
        with self.assertRaisesRegex(ValueError, "uncorrected"):
            apply_storyboard_patch(self.original, {"changes":[]}, diagnostics=d)

    def test_no_repair_without_diagnosed_error(self):
        valid = deepcopy(self.original)
        valid["slides"][0]["title"] = "Trade outlook for 2025"
        self.assertEqual(storyboard_diagnostics(valid), [])


class ContextSupervisorContractTests(unittest.TestCase):
    def setUp(self):
        ir = compile_ir(
            "Export analysis", "# Summary\nData evidence is available.\n"
            "## Action\nConfirm all statements.", ["https://example.org/report"],
            {"rows":3,"sql_row_count":3})
        self.payload = {"objective":"Investigate export trends",
                        "deliverables":["research","pptx"],"uploads":[]}
        self.context = {
            "artifact_ir":ir,
            "goal_contract":{"requirements":[{"id":"g1", "kind":"analysis",
                  "obligation":"Explain export trends", "evidence_needed":"Official values",
                  "priority":5}],"unknowns":[]},
            "summary":{"rows":3,"sql_row_count":3},
        }
        self.package=snapshot_context(
            self.payload,self.context,focus=("powerpoint",))

    def review(self, decision="ready", reqs=None, status="supported"):
        return {"schema_version":1,"decision":decision,
                "coverage":[{"id":"g1","status":status,
                             "evidence_refs":["https://example.org/report"]}],
                "requests":reqs or [],
                "assessment":"Complete source-based investigation requested."}

    def test_requirements_and_provenance_are_immutable(self):
        verdict=validate_context_review(self.review(),package=self.package,
                                        permitted=frozenset({"research"}))
        self.assertEqual(verdict["decision"],"ready")
        self.assertIn("revision",self.package)
        self.context["context_package"]=self.package
        self.assertIn(self.package["revision"],context_brief(self.context))
        invalid=self.review()
        invalid["coverage"][0]["id"]="fabricated"
        with self.assertRaises(ValueError):
            validate_context_review(invalid,package=self.package,
                                    permitted=frozenset({"research"}))
        invalid=self.review()
        invalid["coverage"][0]["evidence_refs"]=["https://invented.invalid"]
        with self.assertRaises(ValueError):
            validate_context_review(invalid,package=self.package,
                                    permitted=frozenset({"research"}))

    def test_later_agent_can_request_prior_authorized_agent(self):
        q={"recipient":"research",
           "question":"Find the official annual value with period and units",
           "reason":"A required result is missing from the approved evidence",
           "blocking":True}
        result=validate_context_review(self.review(
            decision="investigate",reqs=[q],status="partial"),
            package=self.package,permitted=frozenset({"research"}))
        self.assertEqual(result["requests"][0]["recipient"],"research")
        with self.assertRaises(ValueError):
            validate_context_review(result,package=self.package,
                                    permitted=frozenset({"sql_analytics"}))

    def test_ready_cannot_ignore_blocking_gap(self):
        q={"recipient":"research","question":"Find missing annual figures",
           "reason":"Figures required for statistical analysis",
           "blocking":True}
        with self.assertRaises(ValueError):
            validate_context_review(self.review(reqs=[q]),
                                    package=self.package,
                                    permitted=frozenset({"research"}))
        with self.assertRaises(ValueError):
            validate_context_review(self.review(status="unknown"),
                                    package=self.package,
                                    permitted=frozenset({"research"}))

    def test_research_merges_without_losing_existing_evidence(self):
        ctx={"text":"Original measured findings.",
             "sources":["https://example.org/a"]}
        result={"text":"Additional independently verified findings.",
                "sources":["https://example.org/a","https://example.org/b"]}
        self.assertTrue(_merge_validated(
            ctx,recipient="research",result=result,request={}))
        self.assertIn("Original measured findings.",ctx["text"])
        self.assertIn("Additional independently verified",ctx["text"])
        self.assertEqual(ctx["sources"],[
            "https://example.org/a","https://example.org/b"])
        self.assertFalse(_merge_validated(
            ctx,recipient="research",result=result,request={}))




class ActualBackdelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_later_context_supervisor_reopens_research_and_reassesses(self):
        from types import SimpleNamespace
        payload={"objective":"Measure historical export levels from official sources",
                 "deliverables":["research","pptx"],"uploads":[]}
        context={"text":"Original researched narrative should remain intact.",
                 "sources":["https://example.org/original"],
                 "summary":None,
                 "goal_contract":{"requirements":[
                    {"id":"g1","kind":"evidence",
                     "obligation":"Provide historical export level and period",
                     "evidence_needed":"Official year-specific data","priority":5}],
                     "unknowns":[]}}
        request={"recipient":"research",
                 "question":"Find the official measured export figure and exact calendar year",
                 "reason":"The downstream presentation needs a primary measured figure",
                 "blocking":True}
        reviews=[
            {"schema_version":1,"decision":"investigate",
             "coverage":[{"id":"g1","status":"partial",
                          "evidence_refs":["https://example.org/original"]}],
             "requests":[request],
             "assessment":"Missing official export measurement and period."},
            {"schema_version":1,"decision":"ready",
             "coverage":[{"id":"g1","status":"supported",
                          "evidence_refs":["https://example.org/new"]}],
             "requests":[],
             "assessment":"The original and newly retrieved sources support the result."},
        ]
        class FakeStore:
            def __init__(self): self.events=[]
            def publish_cognition(self, *args):
                self.events.append(args)
                return len(self.events)
        store=FakeStore()
        async def researcher(query):
            self.assertIn("New evidence requested",query)
            return {"text":"An official report lists 125 units for 2025, "
                           "subject to methodological limitations.",
                    "sources":["https://example.org/new"]}
        with patch("rizzler.config.Settings.from_env",
                   return_value=SimpleNamespace(
                       gemini_api_key="fake",gemini_model="fake")), \
             patch("rizzler.work_context_intelligence.review_context",
                   new=AsyncMock(side_effect=reviews)) as reviewer:
            result=await converge_context(
                context,payload=payload,store=store,owner="owner",
                jid="job",worker_id="worker",fence=1,
                researcher=researcher,focus=("powerpoint",),
                max_waves=2,client=object())
        self.assertTrue(result["ready"])
        self.assertEqual(reviewer.await_count,2)
        self.assertIn("Original researched narrative",context["text"])
        self.assertIn("official report lists 125",context["text"])
        self.assertIn("https://example.org/new",context["sources"])
        self.assertEqual(context["context_status"],"ready")
        self.assertEqual(len(store.events),2)
        self.assertNotEqual(store.events[0][-1]["revision"],
                            store.events[1][-1]["revision"])


class NativeGeminiCapabilityTests(unittest.TestCase):
    def test_model_can_select_only_approved_native_tools(self):
        from rizzler.gemini_native import validate_native_choice
        decision={"tools":["google_search","url_context"],
                  "thinking_level":"high",
                  "reason":"Recent facts and public URL source context are both needed."}
        self.assertEqual(validate_native_choice(
            decision, permitted=frozenset({"google_search","url_context"})),
            decision)
        with self.assertRaises(ValueError):
            validate_native_choice(decision,
                permitted=frozenset({"google_search"}))
        with self.assertRaises(ValueError):
            validate_native_choice(
                {**decision,"tools":["google_search","private_filesystem"]},
                permitted=frozenset({"google_search","url_context"}))
        with self.assertRaises(ValueError):
            validate_native_choice(
                {**decision,"tools":["google_search","google_search"]},
                permitted=frozenset({"google_search","url_context"}))

    def test_sdk_feature_detection_does_not_invent_capabilities(self):
        from rizzler.gemini_native import native_tools
        class Stub:
            class Tool:
                def __init__(self, **kwargs): self.props = kwargs
            class GoogleSearch: pass
        choice={"tools":["google_search"],
                "thinking_level":"low",
                "reason":"Search for current, public evidence."}
        self.assertEqual(len(native_tools(
            choice,types=Stub,
            permitted=frozenset({"google_search"}))),1)
        with self.assertRaises(RuntimeError):
            native_tools({**choice,"tools":["url_context"]},types=Stub,
                         permitted=frozenset({"url_context"}))


if __name__=="__main__":
    unittest.main()
