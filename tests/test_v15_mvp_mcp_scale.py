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
