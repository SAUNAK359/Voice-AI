"""True Work artifact invocation exercises the cognitive recovery dispatcher.

No paid API calls or mocks of the validator: real markdown bytes, sha256
receipts and file promotion must survive an injected first-render failure.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import shutil
import sys
import unittest
from unittest.mock import AsyncMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rizzler.work_agents import SPECS
from rizzler.work_ir import compile_ir
from rizzler.work_specialists import invoke
from rizzler.work_feedback import EvidenceGap
from rizzler.work_skills import render_one as actual_render


class FakeJobStore:
    def __init__(self,root):
        self.root=Path(root)
        self.entries=[]
        self.publications=[]

    def cognitive_events(self,owner,jid,limit=200):
        return [dict(item) for item in self.entries]

    def publish_cognition(self,jid,worker,fence,agent,kind,payload):
        self.entries.append({"agent":agent,"kind":kind,"payload":dict(payload)})
        return len(self.entries)

    def agent_publish(self,jid,worker,fence,owner,working,receipt):
        target=self.root/"checkpoints"/owner/jid/receipt.name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(working,target)
        self.publications.append(receipt.kind)
        return target


class RealSpecialistRecoveryIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workspace=TemporaryDirectory()
        self.addAsyncCleanup(asyncio.to_thread,self.workspace.cleanup)
        self.store=FakeJobStore(self.workspace.name)
        self.owner="test_owner"
        self.jid="job_12345"
        self.checkpoint=self.store.root/"checkpoints"/self.owner/self.jid
        self.checkpoint.mkdir(parents=True,exist_ok=True)
        self.attempt=self.store.root/"attempts"/"pdf_visual"
        self.attempt.mkdir(parents=True,exist_ok=True)
        self.ir=compile_ir(
            "Source-grounded executive analysis",
            "# Background\nThe project addresses a source-grounded engineering workflow.\n"
            "## Constraints\nAll user facts require verification before publication.\n"
            "## Recommendations\nDeploy only after successful independent tests.",
            [])
        self.context={
            "artifact_ir":self.ir,"summary":None,"sources":[],
            "receipts":{},"preflight":{},"goal_brief":"",
            "context_package":None,"sql_queries":[]}
        self.payload={"objective":"Create a trusted executive Markdown report.",
                      "deliverables":["md"],"uploads":[]}
        self.call_count=0

    async def run_specialist(self):
        return await invoke(
            SPECS["pdf_visual"],self.checkpoint,self.context,{"md"},
            self.payload,self.store,self.owner,
            None,None,self.jid,"worker",1,self.attempt)

    def render_once_failure(self,kind,path,title,content,table,sources):
        self.call_count+=1
        if self.call_count==1:
            raise ValueError("Simulated first render contract error")
        return actual_render(kind,path,title,content,table,sources)

    async def test_cognitive_rerender_recovers_and_publishes_real_checksum(self):
        decision={"action":"rerender",
                  "reason":"The first file write failed before format verification.",
                  "request":None}
        with patch.dict(os.environ,{"GEMINI_API_KEY":"not_a_real_key",
                                    "RIZZLER_V23_MODE":"full"},clear=False), \
             patch("rizzler.work_specialists.render_one",
                   side_effect=self.render_once_failure), \
             patch("rizzler.work_execution_recovery.select_recovery",
                   new=AsyncMock(return_value=decision)):
            result=await self.run_specialist()
        self.assertEqual(self.call_count,2)
        self.assertEqual(self.store.publications,["md"])
        self.assertEqual(result["receipts"][0]["kind"],"md")
        self.assertEqual(result["inspections"]["md"]["repair_attempts"],1)
        target=self.checkpoint/"md.md"
        self.assertTrue(target.is_file())
        from rizzler.artifacts import verify_artifact
        self.assertEqual(verify_artifact(target,"md").sha256,
                         result["receipts"][0]["sha256"])
        attempts=[event for event in self.store.entries
                  if event["agent"]=="recovery_controller"]
        self.assertEqual(len(attempts),1)
        self.assertEqual(attempts[0]["payload"]["action"],"rerender")

    async def test_missing_upstream_evidence_is_delegated_not_fabricated(self):
        decision={"action":"backdelegate",
                  "reason":"A missing user-provided source needs clarification.",
                  "request":{
                      "recipient":"user",
                      "question":"Which original source document should support this factual assertion?",
                      "reason":"A missing source is essential before presenting the claim.",
                      "blocking":True}}
        with patch.dict(os.environ,{"GEMINI_API_KEY":"not_a_real_key",
                                    "RIZZLER_V23_MODE":"full"},clear=False), \
             patch("rizzler.work_specialists.render_one",
                   side_effect=self.render_once_failure), \
             patch("rizzler.work_execution_recovery.select_recovery",
                   new=AsyncMock(return_value=decision)):
            with self.assertRaises(EvidenceGap):
                await self.run_specialist()
        self.assertEqual(self.store.publications,[])


if __name__=="__main__":
    unittest.main()
