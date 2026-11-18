"""V23 HACE, progressive capability fabric, and gated LangMem contracts.

No provider API calls, browser, workspace writes outside temporary directories,
or hidden model reasoning used in these acceptance tests.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rizzler.work_hace import validate, CognitiveDecisionError
from rizzler.work_capability_fabric import (
    Capability, CapabilityFabric, CapabilityContractError, read_only_fabric)


def hierarchy():
    def node(sid,parent,depth,role,deps):
        return {"id":sid,"parent_id":parent,"depth":depth,
                "specialist":role,
                "objective":"Investigate exact requirements and validated domain evidence",
                "required_evidence":["Source records with verifiable provenance"],
                "acceptance":["Specific documented conclusion or explicit uncertainty"],
                "depends_on":deps}
    return {
        "strategy":"Map domain questions then reconcile evidence from deepest branches",
        "source_policy":"uploaded_only",
        "knowledge_gaps":["Research outside uploaded source scope is prohibited"],
        "stages":[
            node("root","",0,"analysis",[]),
            node("domain_a","root",1,"research",["root"]),
            node("domain_b","root",1,"editorial",["root"]),
            node("final_quality","domain_b",2,"quality",
                 ["root","domain_a","domain_b"])],
    }


class HierarchyTests(unittest.TestCase):
    def test_model_plan_is_topological_and_scope_fenced(self):
        d=validate(hierarchy(),policy="uploaded_only")
        self.assertEqual(len(d.stages),4)
        self.assertIn("Domain",d.instruction())
        with self.assertRaises(CognitiveDecisionError):
            validate(hierarchy(),policy="external_allowed")

    def test_forbids_cycles_invented_specialists_and_skipping_parent(self):
        d=hierarchy()
        d["stages"][1]["depends_on"]=["final_quality"]
        with self.assertRaises(CognitiveDecisionError):
            validate(d)
        d=hierarchy()
        d["stages"][2]["specialist"]="unregistered_shell_agent"
        with self.assertRaises(CognitiveDecisionError):
            validate(d)
        d=hierarchy()
        d["stages"][3]["parent_id"]="root"
        with self.assertRaises(CognitiveDecisionError):
            validate(d)

    def test_durable_owner_fenced_hace_checkpoint(self):
        from rizzler.work_store import WorkStore, Missing, Conflict
        with tempfile.TemporaryDirectory() as root:
            store=WorkStore(root)
            job=store.submit("owner_1234",
                "Create a substantial policy report from supplied documents",
                ["md"],"v23-hace-test-123456",[],
                evidence_scope="uploaded_only")
            claim=store.claim("worker_1234",lease_seconds=60)
            store.commit_hace_plan("owner_1234",job["id"],
                                   "worker_1234",claim["fence"],hierarchy())
            self.assertEqual(store.hace_plan("owner_1234",job["id"]),hierarchy())
            with self.assertRaises(Missing):
                store.hace_plan("owner_other",job["id"])
            changed=hierarchy()
            changed["strategy"]="A different strategy that was not committed"
            with self.assertRaises(Conflict):
                store.commit_hace_plan("owner_1234",job["id"],"worker_1234",
                                       claim["fence"],changed)


class ToolFabricTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_parallel_program_with_real_dependencies(self):
        active=peak=0
        async def operation(args):
            nonlocal active,peak
            active+=1;peak=max(peak,active)
            await asyncio.sleep(.02)
            active-=1
            return {"value":args["value"]}
        fab=CapabilityFabric([Capability(
            "safe_read","Read a specific permitted synthetic data record",
            operation,frozenset({"value"}))],max_parallel=2)
        steps=[{"id":f"step_{i}","tool":"safe_read",
                "arguments":{"value":i},"depends_on":[]}
               for i in range(4)]
        got=await fab.execute({"steps":steps},set())
        self.assertEqual(got["status"],"completed")
        self.assertEqual(peak,2)
        self.assertEqual(len(got["results"]),4)

    async def test_authorization_prevents_tool_execution(self):
        calls=[]
        fab=CapabilityFabric([Capability(
            "secret_read","Read private data when explicitly authorized",
            lambda args:calls.append(args) or {"ok":True},
            frozenset(),frozenset({"private"}))])
        step={"steps":[{"id":"attempt","tool":"secret_read",
                        "arguments":{},"depends_on":[]}]}
        with self.assertRaises(PermissionError):
            await fab.execute(step,set())
        self.assertEqual(calls,[])
        self.assertEqual(fab.discover("private",set()),[])

    async def test_owner_approved_evidence_tools_do_not_claim_verification(self):
        fab=read_only_fabric(
            "Investor report contains a factual claim about supply-chain costs.",
            ["https://example.com/source"],
            {"research":"# Research\nInvestigate source provenance."})
        program={"steps":[
            {"id":"inventory","tool":"source_inventory",
             "arguments":{},"depends_on":[]},
            {"id":"evidence","tool":"evidence_lookup",
             "arguments":{"query":"supply-chain"},"depends_on":["inventory"]}]}
        got=await fab.execute(program,set())
        self.assertFalse(got["results"]["inventory"]["source_claims_verified"])
        self.assertEqual(got["results"]["evidence"]["verification"],
                         "unverified_passage_match")
        with self.assertRaises(CapabilityContractError):
            fab.compile({"steps":[{"id":"escape","tool":"shell",
                                   "arguments":{},"depends_on":[]}]},set())


@unittest.skipUnless(importlib.util.find_spec("yaml") is not None,
                     "PyYAML is provided by the optional Deep Agents extra")
class SpecialistPackageTests(unittest.TestCase):
    def test_every_specialist_has_deep_skill_and_valid_manifest(self):
        from rizzler.work_agent_packages import catalog
        found=catalog()
        self.assertEqual(len(found),8)
        self.assertTrue(all(x["max_depth"]==7 for x in found))

    def test_rejects_manifest_tool_escalation(self):
        from rizzler.work_agent_packages import load
        p=load("research")
        self.assertIn("grounded_research",p.tools)
        with self.assertRaises(ValueError):
            load("../../unknown")


@unittest.skipUnless(
    importlib.util.find_spec("cryptography") is not None and
    importlib.util.find_spec("pydantic") is not None,
    "Encrypted LangMem tests require optional memory dependencies")
class LangMemWorkTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_verified_quality_defects_become_owner_memories(self):
        from rizzler.work_langmem import (
            OperationalLesson, consolidate_completed_job, recall)
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{
                "RIZZLER_WORK_ROOT":root,
                "RIZZLER_MEMORY_KEY":"test-only-independent-secret-"+"x"*44,
                "RIZZLER_MEMORY_ENABLED":"1",
                "RIZZLER_LANGMEM_ENABLED":"1"}):
            issue="Slide typography obscures supported quantitative explanations."
            class Store:
                def get(self,owner,jid):
                    return {"status":"completed"}
                def quality_report(self,owner,jid):
                    return {"quality":{"passed":True}}
                def quality_feedback(self,owner,jid):
                    return [{"iteration":0,"findings":[
                        {"kind":"pptx","problem":issue}]}]
            class Manager:
                async def ainvoke(self,messages):
                    return [("memory-1",OperationalLesson(
                        specialist="powerpoint",
                        action="Inspect rendered slide typography before final publication",
                        why="Readable quantitative explanations enable stakeholder understanding",
                        source_issue=issue,confidence=.96))]
            with patch("rizzler.work_deepagents._model",return_value=object()):
                result=await consolidate_completed_job(
                    Store(),"owner_1234","job_1234",
                    SimpleNamespace(request_timeout=20),
                    manager_factory=lambda *a,**kw:Manager())
            self.assertEqual(result["saved"],1)
            self.assertTrue(recall("owner_1234","slide typography quantitative"))
            self.assertEqual(recall("owner_9999","slide typography quantitative"),[])

    async def test_unverified_jobs_cannot_write_operational_memory(self):
        from rizzler.work_langmem import consolidate_completed_job
        class Store:
            def get(self,owner,jid):return {"status":"failed"}
        with patch.dict(os.environ,{
                "RIZZLER_LANGMEM_ENABLED":"1",
                "RIZZLER_MEMORY_ENABLED":"1"}):
            self.assertEqual(
                (await consolidate_completed_job(
                    Store(),"owner_1234","job_1234"))["status"],"not_verified")


if __name__=="__main__":
    unittest.main()
