"""V15 SGLang agentic Work and source-fidelity release regressions.

Never calls external services. Uses a fake SGLang HTTP transport and real native
artifact APIs. Live multimodal/research quality requires separate acceptance.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase, skipUnless
from unittest.mock import patch

from rizzler.work_decision_plane import diagnosis
from rizzler.work_ir import compile_ir
from rizzler.work_sglang import config, decision, complete, SGLangProviderError


@skipUnless(importlib.util.find_spec("httpx"),"Optional HTTP transport unavailable")
class SGLangAgentTests(IsolatedAsyncioTestCase):
    async def test_structured_decisions_use_real_compatible_http_shape(self):
        import httpx
        seen=[]
        def serve(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200,json={
                "choices":[{"message":{"content":'{"approved":true}'}}]})
        transport=httpx.MockTransport(serve)
        original=httpx.AsyncClient
        def factory(**kwargs):
            return original(transport=transport,**kwargs)
        env={"RIZZLER_WORK_LLM_BACKEND":"sglang",
             "RIZZLER_SGLANG_MODEL":"Qwen/Qwen3-4B",
             "RIZZLER_SGLANG_BASE_URL":"http://127.0.0.1:30000/v1"}
        with patch.dict(os.environ,env),patch("httpx.AsyncClient",side_effect=factory):
            schema={"type":"object","properties":{"approved":{"type":"boolean"}},
                    "required":["approved"],"additionalProperties":False}
            result=await decision("Approve after verifying evidence.",schema)
        self.assertEqual(result,{"approved":True})
        self.assertEqual(seen[0]["response_format"]["type"],"json_schema")
        self.assertEqual(seen[0]["model"],"Qwen/Qwen3-4B")
        self.assertFalse(seen[0]["stream"])

    async def test_vlm_page_request_carries_real_png_and_structured_contract(self):
        import httpx
        seen=[]
        def serve(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200,json={"choices":[{"message":{
                "content":'{"pages":[{"page":1,"passed":true,"issues":[]}]}'}}]})
        transport=httpx.MockTransport(serve)
        original=httpx.AsyncClient
        def factory(**kwargs):return original(transport=transport,**kwargs)
        png=b"\x89PNG\r\n\x1a\n"+b"\0"*16
        with patch.dict(os.environ,{"RIZZLER_SGLANG_MODEL":"Qwen/VLM",
                  "RIZZLER_SGLANG_BASE_URL":"http://127.0.0.1:30000/v1"}),\
             patch("httpx.AsyncClient",side_effect=factory):
            output=await complete("Review page one.",images=[png],schema={
                "type":"object","properties":{"pages":{"type":"array"}},
                "required":["pages"]})
        self.assertIn('"passed":true',output)
        body=seen[0]["messages"][1]["content"]
        self.assertEqual(body[1]["type"],"image_url")
        self.assertTrue(body[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    async def test_provider_errors_are_not_misreported_as_success(self):
        import httpx
        transport=httpx.MockTransport(lambda req:httpx.Response(500,text="secret raw provider text"))
        original=httpx.AsyncClient
        with patch.dict(os.environ,{"RIZZLER_SGLANG_MODEL":"Qwen/Test",
                 "RIZZLER_SGLANG_BASE_URL":"http://127.0.0.1:30000/v1"}),\
             patch("httpx.AsyncClient",side_effect=lambda **kw:
                   original(transport=transport,**kw)):
            with self.assertRaisesRegex(SGLangProviderError,"sglang_http_status_500"):
                await decision("Test",{"type":"object"})

    def test_insecure_remote_http_is_rejected(self):
        with patch.dict(os.environ,{"RIZZLER_SGLANG_MODEL":"Qwen/Test",
                 "RIZZLER_SGLANG_BASE_URL":"http://remote.example.org:30000/v1"}):
            with self.assertRaises(SGLangProviderError):config()


class ArtifactFidelityTests(TestCase):
    @skipUnless(importlib.util.find_spec("docx"),"Optional Word renderer unavailable")
    def test_native_docx_preserves_inline_whitespace_and_has_no_markup_leak(self):
        from rizzler.work_skills import render_one
        from rizzler.work_quality import inspect_artifact
        from docx import Document
        content=("# Results\nGross profit **increased** in the West. "
                 "This result uses *source data* and remains qualified by uncertainty.\n"
                 "## Method\nIndependent calculations and original source citations are preserved.")
        ir=compile_ir("Business overview",content,[])
        with TemporaryDirectory() as root,patch.dict(os.environ,{
                "RIZZLER_AGENTIC_ENABLED":"1","RIZZLER_V15_RICH_DOCS":"1"}):
            out=Path(root)/"docx.docx"
            render_one("docx",out,ir.title,ir.content,None,[])
            actual="\n".join(p.text for p in Document(out).paragraphs)
            self.assertIn("Gross profit increased in the West.",actual)
            self.assertIn("source data and remains",actual)
            self.assertNotIn("**increased**",actual)
            qa=inspect_artifact(out,"docx",artifact_ir=ir,visual_required=False)
            self.assertTrue(qa["passed"])

    @skipUnless(importlib.util.find_spec("openpyxl"),"Optional spreadsheet renderer unavailable")
    def test_source_xlsx_formulas_survive_without_conversion(self):
        from openpyxl import Workbook,load_workbook
        from rizzler.work_skills import read_dataset,analyze,render_one
        from rizzler.work_formula import verify_workbook
        from rizzler.work_quality import inspect_artifact
        with TemporaryDirectory() as root:
            source=Path(root)/"original.xlsx"
            wb=Workbook()
            ws=wb.active
            ws.title="Data"
            ws.append(["Region","Revenue_INR","Cost_INR","Original Formula"])
            ws.append(["East",100,60,"=B2-C2"])
            ws.append(["West",200,90,"=B3-C3"])
            wb.save(source)
            headers,rows=read_dataset(source)
            table=(headers,rows)
            summary=analyze(headers,rows)
            ir=compile_ir("Revenue review",
                "# Results\nThe financial data was independently analyzed.\n"
                "## Limits\nAll source formulas remain editable and unaltered.",[],summary)
            result=Path(root)/"report.xlsx"
            render_one("xlsx",result,ir.title,ir.content,table,[],source)
            report=load_workbook(result,read_only=True,data_only=False)
            try:
                self.assertIn("Data",report.sheetnames)
                self.assertIn("Rizzler Data",report.sheetnames)
                self.assertEqual(report["Data"]["D2"].value,"=B2-C2")
                self.assertEqual(report["Data"]["D2"].data_type,"f")
                self.assertEqual(report["Rizzler Financial Insights"]["B2"].value,"INR")
                self.assertIn("₹",report["Rizzler Financial Insights"]["B4"].number_format)
                self.assertNotIn("$",report["Rizzler Financial Insights"]["B4"].number_format)
            finally:report.close()
            self.assertEqual(verify_workbook(result,dataset_summary=summary,
                                             source_path=source)["status"],
                             "independently_verified")
            self.assertTrue(inspect_artifact(result,"xlsx",dataset_rows=2,
                artifact_ir=ir,dataset_summary=summary,
                source_workbook_path=source)["passed"])
            modified=load_workbook(result)
            modified["Data"]["D2"]=40
            modified.save(result)
            with self.assertRaisesRegex(ValueError,"Original workbook cell or formula modified"):
                verify_workbook(result,dataset_summary=summary,source_path=source)

    def test_safe_error_taxonomy_exposes_no_raw_secret(self):
        self.assertEqual(diagnosis(ValueError(
            "Artifact IR sections or source provenance missing")),
            "artifact_provenance_mismatch")
        self.assertEqual(diagnosis(ValueError(
            "provider key=verysecret and user text")),"unspecified_agent_failure")


class IsolatedSpecialistTests(IsolatedAsyncioTestCase):
    async def test_one_failed_specialist_does_not_cancel_sql_sibling(self):
        from rizzler.work_store import WorkStore
        from rizzler.work_worker import WorkWorker
        from rizzler import work_dynamic
        graph={"schema_version":2,"status":"ready","steps":[
            {"id":"research","tool":"research","depends_on":[]},
            {"id":"sql_analytics","tool":"sql_analytics","depends_on":[]},
            {"id":"orchestrator","tool":"orchestrator",
             "depends_on":["research","sql_analytics"]},
            {"id":"pdf_visual","tool":"pdf_visual","depends_on":["orchestrator"]},
            {"id":"quality","tool":"quality","depends_on":[
                "research","sql_analytics","orchestrator","pdf_visual"]}]}
        async def fake_plan(*args,**kwargs):return graph
        async def failed_research(*args,**kwargs):
            await asyncio.sleep(0.01)
            raise ValueError("Artifact IR sections or source provenance missing")
        async def compose(*args,**kwargs):return "# Should not run"
        with TemporaryDirectory() as root,patch.dict(os.environ,{
                "RIZZLER_AGENTIC_ENABLED":"1","RIZZLER_V15_RECOVERY":"0",
                "RIZZLER_V15_COGNITIVE_PREFLIGHT":"off"}),\
             patch.object(work_dynamic,"generate",new=fake_plan):
            store=WorkStore(root)
            upload=store.register_upload("owner","a.csv",
                b"Region,Revenue_INR,Cost_INR\nEast,200,120\nWest,300,180\n")
            jid=store.submit("owner","Analyze data and research industry context",
                 ["md","data_analysis"],"isolated_siblings_001",
                 [upload["id"]],evidence_scope="external_allowed")["id"]
            await WorkWorker(store,composer=compose,researcher=failed_research).once()
            agents={x["agent"]:x for x in store.agent_steps("owner",jid)}
            self.assertEqual(agents["sql_analytics"]["status"],"completed")
            self.assertEqual(agents["research"]["status"],"failed")
            self.assertEqual(store.get("owner",jid)["status"],"failed")
            self.assertEqual(store.artifacts("owner",jid),[])
