"""MVP end-to-end reliability contracts without live provider credentials."""
from __future__ import annotations
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rizzler.source_index import SourceIndex
from rizzler.work_mcp import MCPWorkBridge
from rizzler.work_store import WorkStore, Missing, Conflict
from rizzler.work_worker import worker_parallelism


class MCPWorkContracts(unittest.TestCase):
    def test_owner_scoped_stdio_tools_and_write_authorization(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"RIZZLER_AGENTIC_ENABLED":"1"}):
            store = WorkStore(root)
            read = MCPWorkBridge(store, "owner_001")
            with self.assertRaises(PermissionError):
                read.submit("Prepare the sales presentation", ["pptx"])
            writer = MCPWorkBridge(store, "owner_001", allow_write=True)
            accepted = writer.submit(
                "Research sales operations and create a PowerPoint",
                ["pptx", "md"], evidence_scope="external_allowed",
                idempotency_key="presentation_001")
            self.assertEqual(accepted["status"], "accepted_not_completed")
            jid = accepted["job_id"]
            self.assertEqual(len(read.list_jobs()["jobs"]),1)
            self.assertEqual(read.status(jid)["job"]["status"],"queued")
            self.assertEqual(read.artifacts(jid)["artifacts"],[])
            self.assertEqual(read.events(jid)["events"][0]["stage"],"queued")
            self.assertEqual(read.plan(jid)["status"],"planning")
            self.assertEqual(read.preflight(jid)["status"],"pending")
            self.assertIsNone(read.quality(jid)["quality"])
            self.assertEqual(
                writer.submit("Research sales operations and create a PowerPoint",
                              ["pptx","md"],evidence_scope="external_allowed",
                              idempotency_key="presentation_001")["job_id"],jid)
            with self.assertRaises(Conflict):
                writer.submit("Different objective",["pdf"],
                              idempotency_key="presentation_001")
            with self.assertRaises(Missing):
                MCPWorkBridge(store,"owner_002").status(jid)
            with self.assertRaises(ValueError):
                writer.status("../../private")
            with self.assertRaises(ValueError):
                writer.submit("Objective with no valid formats",["exe"])

    def test_mcp_accepts_indexed_sources_without_cross_owner_leakage(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"RIZZLER_AGENTIC_ENABLED":"1"}):
            store=WorkStore(root)
            entry=SourceIndex(root).register("owner_001","research.md",
                ("## Verified context\nCustom measurements are documented.\n"*24).encode())
            owner=MCPWorkBridge(store,"owner_001",allow_write=True)
            result=owner.submit("Summarize this complete source carefully",["md"],
                                source_ids=[entry["id"]],source_coverage="complete")
            spec=store.specification("owner_001",result["job_id"])
            self.assertEqual(spec["source_ids"],[entry["id"]])
            self.assertEqual(spec["source_coverage"],"complete")
            with self.assertRaises(Missing):
                MCPWorkBridge(store,"owner_002",allow_write=True).submit(
                    "Summarize private source records",["md"],
                    source_ids=[entry["id"]])

    def test_mcp_server_is_import_lazy(self):
        import rizzler.work_mcp
        self.assertTrue(hasattr(rizzler.work_mcp,"create_mcp_server"))


class APISourceContracts(unittest.TestCase):
    def test_http_job_submission_reaches_source_coverage_ledger(self):
        import importlib.util
        if importlib.util.find_spec("httpx") is None:
            self.skipTest("HTTP test client unavailable in dependency-free suite")
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("API extras absent in minimal offline suite")
        from rizzler.work_api import router
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{"RIZZLER_AGENTIC_ENABLED":"1"}):
            store=WorkStore(root)
            source=SourceIndex(root).register("owner_001","source.txt",
                ("Operations context is traceable and complete.\n"*60).encode())
            app=FastAPI()
            app.include_router(router(store,owner_resolver=lambda request:"owner_001"))
            with TestClient(app) as client:
                request={"objective":"Produce an evidence-grounded complete briefing",
                         "deliverables":["md"],
                         "source_ids":[source["id"]],
                         "source_coverage":"complete",
                         "evidence_scope":"uploaded_only"}
                response=client.post("/api/work/jobs",json=request,
                                     headers={"idempotency-key":"source_http_0001"})
                self.assertEqual(response.status_code,202,response.text)
                record=store.specification("owner_001",response.json()["id"])
                self.assertEqual(record["source_ids"],[source["id"]])
                self.assertEqual(record["source_coverage"],"complete")
                self.assertEqual(record["evidence_scope"],"uploaded_only")


class WorkerScaleContracts(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_parallelism_bounded_and_shutdown_drains(self):
        from rizzler import work_worker
        active=[0]
        peak=[0]
        started=[0]
        class FakeWorker:
            def __init__(self, store):pass
            async def once(self):
                started[0]+=1
                active[0]+=1
                peak[0]=max(active[0],peak[0])
                try:
                    await asyncio.sleep(.006)
                    return True
                finally:
                    active[0]-=1
        store=SimpleNamespace(schedule_due=lambda:None)
        with patch.dict(os.environ,{"RIZZLER_WORK_CONCURRENCY":"3"}),\
             patch.object(work_worker,"WorkWorker",FakeWorker):
            task=asyncio.create_task(work_worker.serve(store,interval=.002))
            await asyncio.sleep(.06)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertGreater(started[0],3)
        self.assertEqual(peak[0],3)
        self.assertEqual(active[0],0)

    async def test_invalid_worker_capacity_fails_closed(self):
        for value in ("0","9","3.3","-1","unknown"):
            with patch.dict(os.environ,{"RIZZLER_WORK_CONCURRENCY":value}):
                with self.assertRaises(ValueError):worker_parallelism()


class RepairAndInferenceContracts(unittest.IsolatedAsyncioTestCase):
    async def test_powerpoint_rebuild_never_uses_unbound_source_workbook(self):
        import hashlib
        from unittest.mock import AsyncMock
        from rizzler.contracts import ArtifactReceipt
        from rizzler.work_ir import compile_ir
        from rizzler.work_repair import _rebuild
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{
                "RIZZLER_AGENTIC_ENABLED":"1","RIZZLER_V15_PRESENTATION":"1"}):
            base=Path(root)
            checkpoint=base/"checkpoints";checkpoint.mkdir()
            original=checkpoint/"pptx.pptx"
            original.write_bytes(b"original-artifact-payload")
            receipt=ArtifactReceipt(kind="pptx",name="pptx.pptx",
                sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
                byte_size=original.stat().st_size,verified=True)
            ir=compile_ir("Executive briefing",
                "# Results\nFinancial results were source-checked.\n"
                "## Conclusions\nThe report includes qualified findings.",[])
            context={"receipts":{"pptx":receipt},"artifact_ir":ir,
                     "text":ir.content,"summary":None}
            class Store:
                root=base
                def agent_publish(self,*args):
                    return args[-2]
            async def fake_presentation(path,*args,**kwargs):
                Path(path).write_bytes(b"revised-executive-slide")
            def fake_receipt(path,kind):
                raw=Path(path).read_bytes()
                return ArtifactReceipt(kind=kind,name=kind+"."+kind,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    byte_size=len(raw),verified=True)
            with patch("rizzler.work_repair.verify_checkpoint",return_value=True),\
                 patch("rizzler.work_repair.verify_artifact",side_effect=fake_receipt),\
                 patch("rizzler.work_repair.inspect_artifact",return_value={"passed":True}),\
                 patch("rizzler.work_presentation.make_presentation",
                       new=AsyncMock(side_effect=fake_presentation)):
                result=await _rebuild(Store(),
                    {"owner":"owner_001","id":"a"*32,"fence":1},
                    "worker",checkpoint,context,
                    {"objective":"Prepare slides","deliverables":["pptx"],"uploads":[]},
                    1,ir)
            self.assertIn("pptx",result["artifacts"])

    async def test_configured_private_sglang_requires_authentication(self):
        from rizzler.work_sglang import config,SGLangProviderError
        config_env={
            "RIZZLER_SGLANG_MODEL":"Qwen/Qwen3-4B",
            "RIZZLER_SGLANG_BASE_URL":"http://sglang:30000/v1",
            "RIZZLER_SGLANG_TRUSTED_HTTP_HOSTS":"sglang",
            "RIZZLER_SGLANG_API_KEY":"private_dummy_work_token",
        }
        with patch.dict(os.environ,config_env):
            self.assertEqual(config()[0],"http://sglang:30000/v1")
        with patch.dict(os.environ,{**config_env,"RIZZLER_SGLANG_API_KEY":""}):
            with self.assertRaises(SGLangProviderError):
                config()


class SourceFormulaContracts(unittest.TestCase):
    def test_strict_source_never_silently_treats_formula_as_blank(self):
        import importlib.util
        if importlib.util.find_spec("openpyxl") is None:
            self.skipTest("Native Excel dependency unavailable in minimal offline CI")
        from openpyxl import Workbook,load_workbook
        from rizzler.work_skills import read_dataset
        import shutil
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"formulas.xlsx"
            workbook=Workbook();sheet=workbook.active
            sheet.append(["Revenue_INR","Cost_INR","Profit_INR"])
            sheet.append([120,50,"=A2-B2"])
            workbook.save(path)
            with patch.dict(os.environ,{"RIZZLER_ARTIFACT_QA":"strict"}),\
                 patch.object(shutil,"which",return_value=None):
                with self.assertRaisesRegex(RuntimeError,"requires LibreOffice"):
                    read_dataset(path)
            still=load_workbook(path,data_only=False)
            self.assertEqual(still.active["C2"].value,"=A2-B2")
            still.close()



class CognitiveFeedbackContracts(unittest.IsolatedAsyncioTestCase):
    async def test_failed_cognitive_decisions_leave_owner_scoped_reason_events(self):
        from unittest.mock import AsyncMock
        from rizzler.work_dynamic import WorkModelConfig
        from rizzler.work_preflight import PreflightRejected
        from rizzler import work_dynamic
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{
                "RIZZLER_AGENTIC_ENABLED":"1",
                "RIZZLER_V15_COGNITIVE_PREFLIGHT":"on"}):
            store=WorkStore(root)
            job=store.submit("owner_001","Prepare a substantive editable report",
                             ["md"],"feedback_reason_001")
            claim=store.claim("worker_01",lease_seconds=60)
            config=WorkModelConfig("mock-key","mock-model",45)
            async def rejected(payload,cfg,*,client=None,on_feedback=None):
                for attempt in range(1,4):
                    on_feedback(attempt,"graph_dependency_invalid")
                raise PreflightRejected("preflight_review_exhausted")
            with patch("rizzler.work_preflight.generate_preflight",new=rejected):
                with self.assertRaises(PreflightRejected):
                    await work_dynamic.generate({
                        **claim["payload"],
                        "_cognitive_checkpoint":(
                            store,"owner_001",claim["id"],"worker_01",claim["fence"])
                    },config,client=object())
            lines=store.events("owner_001",job["id"])
            self.assertEqual(len([x for x in lines
                     if x["stage"]=="preflight_revision"]),3)
            with self.assertRaises(Missing):
                store.record_cognitive_feedback("other_owner",job["id"],
                    "worker_01",claim["fence"],1,"graph_dependency_invalid")
            with self.assertRaises(ValueError):
                store.record_cognitive_feedback("owner_001",job["id"],
                    "worker_01",claim["fence"],1,"API_KEY=secret!")
