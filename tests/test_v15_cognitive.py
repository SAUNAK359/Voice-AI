"""V15 cognitive work: offline adversarial contracts and native artifact fixtures."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from rizzler.work_cognition import (
    CognitiveDecisionError, ResearchDirection, validate_research_direction,
    validate_semantic_review, direct_research, review_semantics)
from rizzler.work_ir import compile_ir
from rizzler.work_presentation import (
    validate_storyboard, render_storyboard, compose_storyboard)
from rizzler.work_worker import grounded_research, ResearchEvidenceUnavailable
from rizzler.work_specialists import invoke
from rizzler.work_agents import SPECS

URL="https://www.example.org/source"
STORY={
    "title":"Supply Chains 2026",
    "slides":[
        {"title":"Executive supply-chain findings","layout":"cover",
         "headline":"Evidence-grounded operational review",
         "points":["Data integrity and escalation are core priorities"],
         "secondary":[],"metrics":[],"citations":[],"notes":"Explain the decision context.",
         "chart_x":"","chart_y":""},
        {"title":"Operational issues","layout":"two_column",
         "headline":"Risks require coordinated mitigation",
         "points":["Latency risk drives operational exposure","Independent QA clarifies gaps"],
         "secondary":["Check source reliability","Prioritize high-impact changes"],
         "metrics":[],"citations":[URL],"notes":"Differentiate evidence and recommendations.",
         "chart_x":"","chart_y":""},
        {"title":"Sources and methodology","layout":"sources",
         "headline":"Attribution does not independently establish truth",
         "points":[],"secondary":[],"metrics":[],"citations":[URL],
         "notes":"Source date and original publication require verification.",
         "chart_x":"","chart_y":""},
    ]
}
IR=compile_ir("Supply Chains 2026","# Findings\nOperational evidence 120 units supports review.",[URL])


class DirectionContractTests(unittest.TestCase):
    def test_model_directed_search_and_stop(self):
        output={"action":"search","questions":[
            "What are the official quarterly statistics?"],"reason":"Missing observations"}
        value=validate_research_direction(output,has_evidence=False,searches_remaining=2)
        self.assertEqual(value.action,"search")
        done=validate_research_direction(
            {"action":"finish","questions":[],"reason":"Coverage adequate"},
            has_evidence=True,searches_remaining=0)
        self.assertEqual(done.action,"finish")

    def test_no_grounding_cannot_be_declared_complete(self):
        for d,evidence,budget in (
            ({"action":"finish","questions":[],"reason":"No sources"},False,2),
            ({"action":"search","questions":[],"reason":"No query"},False,2),
            ({"action":"search","questions":["What is the trade balance?"],"reason":"Try"},False,0),
            ({"action":"delete","questions":[],"reason":"Bad"},False,2),
            ({"action":"search","questions":["bad"],"reason":"Too short"},False,2),
            ({"action":"search","questions":["What happened?"]*4,"reason":"Too many"},False,2),
            ({"action":"finish","questions":["What happened?"],"reason":"Bad"},True,2),
        ):
            with self.subTest(d=d):
                with self.assertRaises(CognitiveDecisionError):
                    validate_research_direction(d,has_evidence=evidence,searches_remaining=budget)

    def test_semantic_review_requires_actionable_feedback(self):
        accepted={"passed":True,"findings":[],"summary":"The requested content has been covered."}
        self.assertTrue(validate_semantic_review(accepted)["passed"])
        failed={"passed":False,"findings":[
            {"kind":"presentation","problem":"Executive conclusions are absent"}],
            "summary":"The content lacks an executive story."}
        self.assertFalse(validate_semantic_review(failed)["passed"])
        for bad in (
            {"passed":True,"findings":failed["findings"],"summary":accepted["summary"]},
            {"passed":False,"findings":[],"summary":"Blocked by missing evidence"},
            {"passed":"yes","findings":[],"summary":"Incorrect boolean value"},
        ):
            with self.assertRaises(CognitiveDecisionError):
                validate_semantic_review(bad)


class PresentationTests(unittest.TestCase):
    def test_native_editable_slide_layouts_and_sources(self):
        if importlib.util.find_spec('pptx') is None:
            self.skipTest('Optional python-pptx not installed in no-deps CI')
        story=validate_storyboard(STORY,[URL],content=IR.content)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"executive.pptx"
            meta=render_storyboard(path,story)
            self.assertEqual(meta["slides"],3)
            from pptx import Presentation
            deck=Presentation(path)
            self.assertEqual(len(deck.slides),3)
            self.assertIn("two_column",meta["layouts"])
            visible="\n".join(sh.text for sl in deck.slides for sh in sl.shapes
                              if getattr(sh,"has_text_frame",False))
            self.assertIn("Risks require coordinated mitigation",visible)
            self.assertIn(URL,visible)
            self.assertTrue(path.stat().st_size>1000)

    def test_stale_citations_and_invented_metric_values_rejected(self):
        for mutated in (
            {**STORY,"slides":[{**STORY["slides"][0],
                "citations":["https://unapproved.example/"]},*STORY["slides"][1:]]},
            {**STORY,"slides":[STORY["slides"][0],{
                **STORY["slides"][1],
                "metrics":[{"label":"Imaginary","value":"9999999","unit":"USD"}]},
                STORY["slides"][2]]},
            {**STORY,"slides":[{**STORY["slides"][0],"layout":"bullets"},
                                *STORY["slides"][1:]]},
            {**STORY,"slides":STORY["slides"][:2]},
        ):
            with self.subTest(slides=repr(mutated)[:120]):
                with self.assertRaises(CognitiveDecisionError):
                    validate_storyboard(mutated,[URL],content=IR.content)

    def test_dataset_chart_must_use_actual_columns(self):
        if importlib.util.find_spec('pptx') is None:
            self.skipTest('Optional python-pptx not installed in no-deps CI')
        table=(["Category","Amount"],[["Engineering",35],["Electronics",48]])
        proposed={**STORY,"slides":[STORY["slides"][0],
            {**STORY["slides"][1],"layout":"chart",
             "chart_x":"Category","chart_y":"Amount"},STORY["slides"][2]]}
        validate_storyboard(proposed,[URL],content=IR.content,table=table)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"chart.pptx"
            render_storyboard(path,proposed,table=table)
            from pptx import Presentation
            self.assertTrue(any(getattr(shape,"has_chart",False)
                for slide in Presentation(path).slides for shape in slide.shapes))
        with self.assertRaises(CognitiveDecisionError):
            validate_storyboard(proposed,[URL],content=IR.content)


class CognitiveIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_receives_research_evidence(self):
        captured=[]
        async def composer(objective,summary):
            captured.append(objective)
            return "# Report\n\n## Results\nA substantive report on verified evidence."
        context={"objective":"Make a substantive presentation",
                 "text":"The documented research figure is 120 units.",
                 "sources":[URL],"summary":None}
        result=await invoke(
            SPECS["orchestrator"],Path("/tmp"),context,{"pptx"},
            {"objective":"Make a substantive presentation"},None,"owner",
            composer,None,"jid","worker",1,Path("/tmp"))
        self.assertIn("120 units",captured[0])
        self.assertIn(URL,captured[0])
        self.assertIn("substantive",result["text"])

    async def test_research_director_has_no_keyword_based_fallback(self):
        cfg=SimpleNamespace(gemini_api_key="mock",gemini_model="fake",request_timeout=40)
        with patch("rizzler.work_cognition.structured_decision",
                   new=AsyncMock(return_value={
                       "action":"search","questions":["What are the official quarterly statistics?"],
                       "reason":"Need official evidence"})):
            result=await direct_research("Explore external trade",cfg,
                rounds_remaining=2,evidence=[],observations=[])
        self.assertEqual(result.action,"search")
        self.assertEqual(len(result.questions),1)

    async def test_semantic_qa_receives_original_objective(self):
        cfg=SimpleNamespace(gemini_api_key="mock",gemini_model="fake",request_timeout=40)
        mock=AsyncMock(return_value={
            "passed":False,
            "findings":[{"kind":"executive","problem":"Requested recommendations are missing"}],
            "summary":"The research has not been converted into decisions."})
        with patch("rizzler.work_cognition.structured_decision",new=mock):
            result=await review_semantics("Write strategic recommendations",
                IR.content,[URL],["pptx"],{"pptx":{"checks":["file_opens"]}},cfg)
        self.assertFalse(result["passed"])
        self.assertIn("Write strategic recommendations",mock.await_args.args[0])

    async def test_complete_research_to_editable_powerpoint_through_real_workstore(self):
        if importlib.util.find_spec('pptx') is None:
            self.skipTest('Optional python-pptx not installed in no-deps CI')
        from rizzler.work_worker import WorkWorker
        from rizzler.work_store import WorkStore
        from pptx import Presentation
        graph={"schema_version":2,"status":"ready","steps":[
            {"id":"research","tool":"research","depends_on":[],"thinking_level":"high"},
            {"id":"orchestrator","tool":"orchestrator",
             "depends_on":["research"],"thinking_level":"high"},
            {"id":"powerpoint","tool":"powerpoint",
             "depends_on":["orchestrator"],"thinking_level":"high"},
            {"id":"quality","tool":"quality",
             "depends_on":["research","orchestrator","powerpoint"],"thinking_level":"high"}]}
        used=[]
        async def research(_objective):
            return {"text":("Official operational figures include 120 units and "
                    "an analysis of supply-chain performance that requires "
                    "careful decision-making and transparent qualifications."),
                    "sources":[URL]}
        async def compose(objective,_summary):
            used.append(objective)
            return ("# Supply chain evidence\n\n## Stakeholder analysis\n"
                    "Operational statistics show 120 units. The report differentiates "
                    "verified source records from editorial interpretation.\n\n"
                    "## Recommendations\nPrioritize source verification and "
                    "incremental response planning.")
        async def plan(_payload,_cfg):
            return graph
        with tempfile.TemporaryDirectory() as root,\
             patch.dict("os.environ",{
                "RIZZLER_AGENTIC_ENABLED":"1",
                "RIZZLER_ARTIFACT_QA":"structural",
                "RIZZLER_V15_PRESENTATION":"1",
                "RIZZLER_V15_RECOVERY":"0"}),\
             patch("rizzler.work_dynamic.generate",new=plan),\
             patch("rizzler.work_dynamic.WorkModelConfig.from_env",
                   return_value=SimpleNamespace(gemini_api_key="mock",
                                                gemini_model="mock",
                                                request_timeout=40)),\
             patch("rizzler.work_presentation.compose_storyboard",
                   new=AsyncMock(return_value=STORY)):
            store=WorkStore(root)
            job=store.submit("owner","Produce an executive supply chain presentation",
                 ["pptx"],"full_v15_presentation_0001",[])
            self.assertTrue(await WorkWorker(store,composer=compose,researcher=research).once())
            saved=store.get("owner",job["id"])
            self.assertEqual(saved["status"],"completed",saved.get("error_code"))
            self.assertIn("120 units",used[0])
            files=store.artifacts("owner",job["id"])
            self.assertEqual([x["kind"] for x in files],["pptx"])
            path,_=store.artifact("owner",files[0]["id"])
            self.assertEqual(len(Presentation(path).slides),3)
            qa=store.quality_report("owner",job["id"])
            self.assertTrue(qa["quality"]["passed"])

    async def test_model_directed_recovery_retries_only_the_failed_specialist(self):
        from rizzler.work_worker import WorkWorker
        from rizzler.work_store import WorkStore
        graph={"schema_version":2,"status":"ready","steps":[
            {"id":"orchestrator","tool":"orchestrator","depends_on":[],"thinking_level":"high"},
            {"id":"pdf_visual","tool":"pdf_visual",
             "depends_on":["orchestrator"],"thinking_level":"high"},
            {"id":"quality","tool":"quality",
             "depends_on":["orchestrator","pdf_visual"],"thinking_level":"high"}]}
        state={"calls":0}
        async def composer(_objective,_summary):
            state["calls"]+=1
            if state["calls"]==1:
                raise TimeoutError("simulated transient model outage")
            return ("# Recovery succeeded\n\n## Findings\n"
                    "The model-supervised retry produced a substantive operational "
                    "report with relevant findings and explicit limitations.")
        async def research(_objective):
            raise AssertionError("Research was not selected")
        async def generate(_payload,_cfg):
            return graph
        advice=AsyncMock(return_value={
            "action":"retry","thinking_level":"high",
            "reason":"A short provider timeout warrants one bounded retry."})
        with tempfile.TemporaryDirectory() as root,\
             patch.dict("os.environ",{
                 "RIZZLER_AGENTIC_ENABLED":"1",
                 "RIZZLER_ARTIFACT_QA":"structural",
                 "RIZZLER_V15_RECOVERY":"1"}),\
             patch("rizzler.work_dynamic.generate",new=generate),\
             patch("rizzler.work_dynamic.WorkModelConfig.from_env",
                   return_value=SimpleNamespace(gemini_api_key="",request_timeout=40,
                                                gemini_model="mock")) ,\
             patch("rizzler.work_cognition.decide_stage_recovery",new=advice):
            store=WorkStore(root)
            job=store.submit("owner","Produce a professional operational report",
                             ["md"],"retry_v15_0001",[])
            self.assertTrue(await WorkWorker(store,composer=composer,researcher=research).once())
            saved=store.get("owner",job["id"])
            self.assertEqual(saved["status"],"completed",saved.get("error_code"))
            stages={row["agent"]:row for row in store.agent_steps("owner",job["id"])}
            self.assertEqual(stages["orchestrator"]["attempt"],2)
            self.assertEqual(stages["quality"]["attempt"],1)
            self.assertEqual(advice.await_count,1)
            self.assertEqual(state["calls"],2)

    async def test_model_abort_does_not_retry_or_claim_success(self):
        from rizzler.work_worker import WorkWorker
        from rizzler.work_store import WorkStore
        graph={"schema_version":2,"status":"ready","steps":[
            {"id":"orchestrator","tool":"orchestrator","depends_on":[],"thinking_level":"high"},
            {"id":"pdf_visual","tool":"pdf_visual",
             "depends_on":["orchestrator"],"thinking_level":"high"},
            {"id":"quality","tool":"quality",
             "depends_on":["orchestrator","pdf_visual"],"thinking_level":"high"}]}
        calls={"n":0}
        async def composer(_objective,_summary):
            calls["n"]+=1
            raise TimeoutError("simulated provider outage")
        async def generate(_payload,_cfg):
            return graph
        with tempfile.TemporaryDirectory() as root,\
             patch.dict("os.environ",{
                 "RIZZLER_AGENTIC_ENABLED":"1",
                 "RIZZLER_ARTIFACT_QA":"structural",
                 "RIZZLER_V15_RECOVERY":"1"}),\
             patch("rizzler.work_dynamic.generate",new=generate),\
             patch("rizzler.work_dynamic.WorkModelConfig.from_env",
                   return_value=SimpleNamespace(gemini_api_key="",request_timeout=40,
                                                gemini_model="mock")),\
             patch("rizzler.work_cognition.decide_stage_recovery",
                   new=AsyncMock(return_value={
                       "action":"abort","thinking_level":"high",
                       "reason":"Provider is unavailable; further attempts are unhelpful."})):
            store=WorkStore(root)
            job=store.submit("owner","Produce a useful operational report",
                             ["md"],"retry_v15_abort_0001",[])
            self.assertTrue(await WorkWorker(store,composer=composer,researcher=None).once())
            result=store.get("owner",job["id"])
            self.assertEqual(result["status"],"failed")
            self.assertEqual(result["error_code"],"provider_or_agent_timeout")
            self.assertEqual(calls["n"],1)
            self.assertEqual(store.artifacts("owner",job["id"]),[])

    async def test_grounded_research_chosen_by_model(self):
        if importlib.util.find_spec('google') is None or importlib.util.find_spec('google.genai') is None:
            self.skipTest('Optional google-genai not installed in no-deps CI')
        from google import genai
        from rizzler.work_cognition import ResearchDirection
        response=SimpleNamespace(
            text="The provider grounded evidence is substantive and provides official figures for this test.",
            candidates=[])
        mock_client=SimpleNamespace(aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=AsyncMock(return_value=response)),
            aclose=AsyncMock()))
        record={"url":URL,"title":"Official evidence","publisher":"example.org"}
        with patch.object(genai,"Client",return_value=mock_client),\
             patch("rizzler.work_cognition.direct_research",
                   new=AsyncMock(side_effect=[
                       ResearchDirection("search",("What are the official export figures?",),"Need data"),
                       ResearchDirection("finish",(),"Source coverage adequate")])),\
             patch("rizzler.research_evidence.source_records",return_value=[record]),\
             patch("rizzler.production_guard.reserve_provider_call"),\
             patch("rizzler.work_dynamic.WorkModelConfig.from_env",return_value=
                   SimpleNamespace(gemini_api_key="mock",gemini_model="mock",request_timeout=40)):
            result=await grounded_research("Research the latest import and export position.")
        self.assertEqual(result["sources"],[URL])
        self.assertIn("official export figures",result["text"])
        self.assertEqual(result["evidence_summary"]["grounded_queries"],1)
        self.assertEqual(mock_client.aio.models.generate_content.await_count,1)

    async def test_unavailable_grounding_blocks_without_fabricated_sources(self):
        if importlib.util.find_spec('google') is None or importlib.util.find_spec('google.genai') is None:
            self.skipTest('Optional google-genai not installed in no-deps CI')
        from google import genai
        from rizzler.work_cognition import ResearchDirection
        mock_client=SimpleNamespace(aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=AsyncMock(return_value=
                SimpleNamespace(text="Some irrelevant content",candidates=[]))),
            aclose=AsyncMock()))
        plan=AsyncMock(side_effect=[
            ResearchDirection("search",("What official source is available?",),"Need source"),
            ResearchDirection("block",(),"No trusted sources")])
        with patch.object(genai,"Client",return_value=mock_client),\
             patch("rizzler.work_cognition.direct_research",new=plan),\
             patch("rizzler.production_guard.reserve_provider_call"),\
             patch("rizzler.work_dynamic.WorkModelConfig.from_env",return_value=
                   SimpleNamespace(gemini_api_key="mock",gemini_model="mock",request_timeout=40)):
            with self.assertRaises(ResearchEvidenceUnavailable):
                await grounded_research("Research current trade statistics")
        self.assertEqual(mock_client.aio.aclose.await_count,1)


if __name__=="__main__":
    unittest.main()
