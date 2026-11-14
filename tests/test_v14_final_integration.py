"""Full mocked-Gemini job execution and real fenced repair publication tests."""
import asyncio
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from rizzler.work_store import WorkStore
from rizzler.work_worker import WorkWorker
from rizzler.work_ir import compile_ir
from rizzler.work_skills import render_one
from rizzler.artifacts import verify_artifact
from rizzler.work_agents import verify_checkpoint

class WorkIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_one_model_planned_job_completes_with_browsable_real_artifact(self):
        graph={"schema_version":2,"status":"ready","steps":[
            {"id":"orchestrator","tool":"orchestrator","depends_on":[],"thinking_level":"high"},
            {"id":"pdf_visual","tool":"pdf_visual","depends_on":["orchestrator"],"thinking_level":"medium"},
            {"id":"quality","tool":"quality","depends_on":["orchestrator","pdf_visual"],"thinking_level":"high"}]}
        async def generate(payload,cfg):return graph
        async def compose(objective,summary):
            return "# Supply chain performance\n\n## Executive summary\nThe delivery pattern shows verified operations observations. This is sample evidence for integration testing only."
        async def research(objective):return {"text":"unused","sources":[]}
        with tempfile.TemporaryDirectory() as root,\
             patch.dict(os.environ,{"RIZZLER_AGENTIC_ENABLED":"1","RIZZLER_ARTIFACT_QA":"structural"}),\
             patch("rizzler.work_dynamic.generate",new=generate),\
             patch("rizzler.work_dynamic.WorkModelConfig.from_env",return_value=object()):
            store=WorkStore(root)
            job=store.submit("owner","Create a supply chain executive report",
                             ["md"],"full_job_test_001",[])
            worked=await WorkWorker(store,composer=compose,researcher=research).once()
            self.assertTrue(worked)
            result=store.get("owner",job["id"])
            self.assertEqual(result["status"],"completed",result.get("error_code"))
            files=store.artifacts("owner",job["id"])
            self.assertEqual([f["kind"] for f in files],["md"])
            path,info=store.artifact("owner",files[0]["id"])
            self.assertIn("Supply chain performance",path.read_text())
            report=store.quality_report("owner",job["id"])
            self.assertTrue(report["quality"]["passed"])

    async def test_repair_preserves_previous_versions_and_fences_publication(self):
        from rizzler.work_repair import _rebuild
        with tempfile.TemporaryDirectory() as root,\
             patch.dict(os.environ,{"RIZZLER_AGENTIC_ENABLED":"1"}):
            store=WorkStore(root)
            job=store.submit("owner","Create a revised operational report",["md"],"revision_job_001",[])
            claim=store.claim("worker-one")
            self.assertEqual(claim["id"],job["id"])
            old=compile_ir("Operational Report","# Overview\nThe original supply chain evidence was recorded.",[],None)
            new=compile_ir("Operational Report","# Overview\nThe revised supply chain evidence is presented clearly with a detailed executive summary.",[],None)
            original=Path(root)/"attempts"/"owner"/job["id"]/str(claim["fence"])/"pdf_visual"/"md.md"
            original.parent.mkdir(parents=True,exist_ok=True)
            render_one("md",original,old.title,old.content,None,[])
            receipt=verify_artifact(original,"md")
            store.agent_publish(job["id"],"worker-one",claim["fence"],"owner",original,receipt)
            checkpoint=Path(root)/"checkpoints"/"owner"/job["id"]
            context={"artifact_ir":old,"receipts":{"md":receipt},"summary":None,"text":old.content}
            audit=await _rebuild(store,claim,"worker-one",checkpoint,context,
                                 {"uploads":[]},1,new)
            self.assertEqual(audit["prior_ir_sha256"],old.sha256)
            self.assertEqual(context["artifact_ir"].sha256,new.sha256)
            preserved=Path(root)/"quality_versions"/"owner"/job["id"]/"revision-1"/"md.md"
            self.assertIn("original",preserved.read_text())
            revised=checkpoint/"md.md"
            self.assertIn("revised",revised.read_text())
            self.assertTrue(verify_checkpoint(revised,context["receipts"]["md"]))
if __name__=="__main__":unittest.main()
