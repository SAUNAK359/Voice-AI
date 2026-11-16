"""MVP acceptance: governed MCP, source handoff, bounded concurrency and native files.

No external credentials. Live SGLang/grounding/quality release uses the Colab
acceptance harness; these tests verify the real API, ledger and native formats.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from rizzler.work_mcp import configured, invoke, verify_args
from rizzler.work_mcp_research import MCPEvidenceMissing, research as mcp_research
from rizzler.work_store import WorkStore
from rizzler.source_index import SourceIndex

SERVER=[{"alias":"web_tools","url":"https://mcp.example.org/mcp","tools":[
    {"name":"search","description":"Find factual information from an approved site",
     "arguments":{"query":"str"},"risk":"read_only"}]}]
CONFIG={"RIZZLER_MCP_SERVERS_JSON":json.dumps(SERVER),
        "RIZZLER_MCP_RESEARCH_TOOL":"mcp.web_tools.search"}


class MCPPolicy(unittest.TestCase):
    def test_declared_read_only_skill_contract_and_safe_urls(self):
        with patch.dict(os.environ,CONFIG):
            tools=configured()
            self.assertEqual(list(tools),["mcp.web_tools.search"])
            self.assertEqual(tools["mcp.web_tools.search"].arguments,{"query":"str"})
            verify_args({"query":"supply chain 2026"},{"query":"str"})
            with self.assertRaises(ValueError):
                verify_args({"query":" "},{"query":"str"})
            with self.assertRaises(ValueError):
                verify_args({"target":"secret"},{"query":"str"})
        write=json.loads(json.dumps(SERVER))
        write[0]["tools"][0]["risk"]="external_action"
        with patch.dict(os.environ,{"RIZZLER_MCP_SERVERS_JSON":json.dumps(write)}):
            with self.assertRaises(ValueError):configured()
        write[0]["tools"][0]["risk"]="read_only"
        write[0]["url"]="http://metadata.google.internal/latest"
        with patch.dict(os.environ,{"RIZZLER_MCP_SERVERS_JSON":json.dumps(write)}):
            with self.assertRaises(ValueError):configured()


class MCPExecution(unittest.IsolatedAsyncioTestCase):
    async def test_provenance_is_never_mistaken_for_source_verification(self):
        async def executor(spec,args):
            self.assertEqual(spec.name,"search")
            self.assertEqual(args,{"query":"2026 India's export figures"})
            return {"text":"Official report outlines export categories in context.",
                    "structured":{"sources":["https://example.org/data",
                      "http://localhost/admin","https://example.org/data"]}}
        with patch.dict(os.environ,CONFIG):
            found=await invoke("mcp.web_tools.search",
                               {"query":"2026 India's export figures"},
                               executor=executor)
            self.assertEqual(found["sources"],["https://example.org/data"])
            self.assertFalse(found["verified"])
            self.assertEqual(found["provenance"],"configured_mcp_server_unverified")
            with self.assertRaises(PermissionError):
                await invoke("mcp.unknown.read",{"query":"secrets"},executor=executor)

    async def test_model_directed_mcp_research_needs_real_citation_records(self):
        from rizzler.work_cognition import ResearchDirection
        cfg=SimpleNamespace(gemini_api_key="",gemini_model="fake",request_timeout=45)
        responses=[
            ResearchDirection("search",("Find publicly attributed export values in 2026",),
                              "Evidence required"),
            ResearchDirection("finish",(),"Research sufficiently covered")]
        async def lookup(*args,**kwargs):
            return {"text":"The published sources describe export and import statistics "
                           "with dates and stated methodology. The claim remains unverified.",
                    "sources":["https://example.org/report"],"verified":False}
        with patch.dict(os.environ,CONFIG),\
             patch("rizzler.work_mcp_research.direct_research",new=AsyncMock(side_effect=responses)),\
             patch("rizzler.work_mcp_research.invoke",new=lookup):
            result=await mcp_research("Study India's trade statistics",cfg)
        self.assertEqual(result["sources"],["https://example.org/report"])
        self.assertTrue(result["evidence_summary"]["model_coverage_accepted"])
        self.assertEqual(result["evidence_summary"]["citation_verification"],
                         "tool_attribution_only")

    async def test_mcp_research_refuses_sourceless_results(self):
        from rizzler.work_cognition import ResearchDirection
        cfg=SimpleNamespace(gemini_api_key="",gemini_model="fake",request_timeout=45)
        async def bad(*args,**kwargs):
            return {"text":"A detailed report without any attributable sources.",
                    "sources":[]}
        with patch.dict(os.environ,CONFIG),\
             patch("rizzler.work_mcp_research.direct_research",new=AsyncMock(
                 return_value=ResearchDirection("search",("Find accurate source facts",),"Need data"))),\
             patch("rizzler.work_mcp_research.invoke",new=bad):
            with self.assertRaises(MCPEvidenceMissing):
                await mcp_research("Research the latest statistics",cfg,max_rounds=1)

    async def test_authenticated_voice_delegates_mcp_evidence_to_work(self):
        from rizzler.agent_runtime import AgentRuntime, discover
        from rizzler.config import Settings
        with tempfile.TemporaryDirectory() as root,\
             patch.dict(os.environ,{"RIZZLER_AGENTIC_ENABLED":"1",**CONFIG}):
            store=WorkStore(root)
            runtime=AgentRuntime(store,Settings(
                access_key="local-test-key-with-good-entropy-abcdef",
                gemini_api_key="not-real"))
            self.assertIn("mcp.web_tools.search",discover(store))
            result=await runtime.execute(
                {"name":"work.submit","arguments":{"deliverables":["pptx","pdf"]}},
                "owner_mcp_001","Create a sourced PowerPoint and PDF",
                "nonce_01",2,0,[],[],[],
                [{"tool":"mcp.web_tools.search",
                  "text":"An official overview was found with dates and source qualifications.",
                  "sources":["https://example.org/report"],
                  "provenance":"configured_mcp_server_unverified"}])
            job=result["job"]
            specification=store.specification("owner_mcp_001",job["id"])
            sources=specification["payload"]["source_ids"]
            self.assertEqual(len(sources),1)
            self.assertIn("tool_evidence_",SourceIndex(root).list("owner_mcp_001")[0]["name"])
            with self.assertRaises(Exception):
                store.get("another_owner",job["id"])


@unittest.skipUnless(importlib.util.find_spec("fastapi"),"FastAPI test dependency missing")
class WorkAPIHandoff(unittest.TestCase):
    def test_selected_source_documents_reach_202_job(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from rizzler.work_api import router
        with tempfile.TemporaryDirectory() as root,\
             patch.dict(os.environ,{"RIZZLER_AGENTIC_ENABLED":"1"}):
            store=WorkStore(root)
            doc=SourceIndex(root).register("owner_api_01","facts.txt",
                b"A documented observation with a cited underlying report. "*12)
            app=FastAPI()
            app.include_router(router(store,owner_resolver=lambda req:
                req.headers.get("x-verified-owner","no_owner")))
            with TestClient(app) as client:
                headers={"x-verified-owner":"owner_api_01",
                         "idempotency-key":"owner_api_source_job_001"}
                res=client.post("/api/work/jobs",headers=headers,
                    json={"objective":"Make a source-only executive report",
                          "deliverables":["pdf","pptx"],
                          "source_ids":[doc["id"]],
                          "source_coverage":"complete",
                          "evidence_scope":"uploaded_only"})
                self.assertEqual(res.status_code,202,res.text)
                specification=store.specification("owner_api_01",res.json()["id"])
                self.assertEqual(specification["payload"]["source_ids"],[doc["id"]])
                self.assertEqual(specification["payload"]["source_coverage"],"complete")
                self.assertEqual(len(specification["payload"]["source_refs"]),1)
                forbidden=client.post("/api/work/jobs",headers={
                    "x-verified-owner":"other_owner",
                    "idempotency-key":"other_owner_source_job_002"},
                    json={"objective":"Make a PDF report",
                          "deliverables":["pdf"],"source_ids":[doc["id"]]})
                self.assertEqual(forbidden.status_code,404)
                self.assertEqual(len(store.list_jobs("other_owner")),0)


class WorkerPool(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_parallel_workers_and_graceful_drain(self):
        from rizzler import work_worker
        active=0
        peak=0
        stop=asyncio.Event()
        async def fake_once(self):
            nonlocal active,peak
            active+=1
            peak=max(peak,active)
            if peak>=3:stop.set()
            await asyncio.sleep(0.04)
            active-=1
            return True
        with tempfile.TemporaryDirectory() as root,\
             patch.object(work_worker.WorkWorker,"once",new=fake_once):
            await work_worker.serve(WorkStore(root),interval=0.05,
                                     concurrency=3,stop=stop)
        self.assertEqual(peak,3)
        self.assertEqual(active,0)

    async def test_sources_can_be_synthesized_via_sglang_without_gemini(self):
        from rizzler.work_corpus import _summarize
        response="# Evidence\nSource paragraph retained.\n# Findings\nThe note is source-bound."
        cfg=SimpleNamespace(gemini_api_key="",gemini_model="none",request_timeout=45)
        with patch.dict(os.environ,{"RIZZLER_WORK_LLM_BACKEND":"sglang"}),\
             patch("rizzler.work_sglang.complete",new=AsyncMock(return_value=response)),\
             patch("rizzler.production_guard.reserve_provider_call"):
            text=await _summarize(None,cfg,"Explain the source", "Source says X.")
        self.assertEqual(text,response)


@unittest.skipUnless(all(importlib.util.find_spec(name)
                     for name in ("docx","pptx","openpyxl","reportlab")),
                     "Native artifact dependencies unavailable")
class ResearchArtifactMVP(unittest.IsolatedAsyncioTestCase):
    async def test_real_research_to_all_documents_and_zip(self):
        from rizzler.work_worker import WorkWorker
        from rizzler.work_quality import inspect_artifact
        from rizzler.work_dynamic import VERSION
        from rizzler.work_presentation import validate_storyboard
        source="https://example.org/research"
        graph={"schema_version":VERSION,"status":"ready","steps":[
            {"id":"research","tool":"research","depends_on":[],"thinking_level":"high"},
            {"id":"orchestrator","tool":"orchestrator","depends_on":["research"],"thinking_level":"high"},
            {"id":"powerpoint","tool":"powerpoint","depends_on":["orchestrator"],"thinking_level":"high"},
            {"id":"word","tool":"word","depends_on":["orchestrator"],"thinking_level":"medium"},
            {"id":"excel","tool":"excel","depends_on":["orchestrator"],"thinking_level":"medium"},
            {"id":"pdf_visual","tool":"pdf_visual",
             "depends_on":["orchestrator","powerpoint","word","excel"],
             "thinking_level":"medium"},
            {"id":"quality","tool":"quality","depends_on":[
                "research","orchestrator","powerpoint","word","excel","pdf_visual"],
             "thinking_level":"high"}]}
        storyboard={"title":"Grounded executive review","slides":[{
            "title":title,"layout":layout,
            "headline":"Evidence-based business intelligence overview",
            "points":["Attributed observations and methodological constraints."],
            "secondary":[],"metrics":[],
            "citations":[source] if layout=="sources" else [],
            "notes":"Explain the evidence limitations and conclusions.",
            "chart_x":"","chart_y":""}
            for title,layout in (("Executive overview","cover"),
                                 ("Analysis and implications","bullets"),
                                 ("Conclusion","closing"),
                                 ("Source provenance","sources"))]}
        async def fake_plan(*args,**kwargs):return graph
        async def fake_research(_):
            return {"text":("# Original research\nAn attributed official research "
                "overview from a trusted publisher identifies underlying trends and "
                "cautions against conflating financial periods. Citation: "+source),
                "sources":[source],"evidence_summary":{
                    "citation_verification":"provider_attribution_only"}}
        async def fake_compose(objective,_):
            self.assertIn("Original research",objective)
            return ("# Executive summary\nThe cited source provides useful historical "
                    "context with clear methodological limitations. "
                    "This analysis distinguishes observations from recommendations.\n\n"
                    "## Research findings\nThe attributed source reports broad trends "
                    "and uncertainty. The relevant figures must be independently "
                    "validated against the original publication before use.\n\n"
                    "## Risks and caveats\nOnly provider citations are known; source "
                    "documents were not independently fetched or fact-checked.\n\n"
                    "## Recommendations\nReview publication dates, reconcile evidence "
                    "and revisit the decisions when verified primary data is available.")
        with tempfile.TemporaryDirectory() as root,\
             patch.dict(os.environ,{
                "RIZZLER_AGENTIC_ENABLED":"1",
                "RIZZLER_V15_COGNITIVE_PREFLIGHT":"off",
                "RIZZLER_ARTIFACT_QA":"structural",
                "RIZZLER_V15_RECOVERY":"0",
                "RIZZLER_V15_PRESENTATION":"1"}),\
             patch("rizzler.work_dynamic.generate",new=fake_plan),\
             patch("rizzler.work_presentation.compose_storyboard",
                   new=AsyncMock(return_value=storyboard)):
            store=WorkStore(root)
            job=store.submit("owner_mvp_01","Research and generate a complete multi-format report",
                    ["research","pptx","docx","xlsx","pdf","md","zip"],
                    "research_artifact_mvp_001",[])
            self.assertTrue(await WorkWorker(store,composer=fake_compose,
                                              researcher=fake_research).once())
            record=store.get("owner_mvp_01",job["id"])
            self.assertEqual(record["status"],"completed",
                             {"error":record["error_code"],
                              "steps":store.agent_steps("owner_mvp_01",job["id"]),
                              "events":store.events("owner_mvp_01",job["id"])})
            files=store.artifacts("owner_mvp_01",job["id"])
            self.assertEqual({x["kind"] for x in files},
                             {"pptx","docx","xlsx","pdf","md","zip"})
            for artifact in files:
                path,receipt=store.artifact("owner_mvp_01",artifact["id"])
                self.assertGreater(path.stat().st_size,10)
                self.assertTrue(inspect_artifact(path,artifact["kind"])["passed"])
            self.assertTrue(store.quality_report("owner_mvp_01",job["id"])
                            ["quality"]["passed"])


if __name__=="__main__":unittest.main()
