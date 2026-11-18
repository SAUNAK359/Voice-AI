"""V23: hierarchical specialist packages, concurrent microprograms and LangMem."""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rizzler.work_agents import SPECS
from rizzler.work_hace import (
    HACEContractError, validate_program, execute_program, fingerprint)
from rizzler.work_skill_packages import load_package, skill_context
from rizzler.work_procedural_memory import (
    ProceduralLedger, from_environment, delete_all_for_owner)


class SkillPackages(unittest.TestCase):
    def test_all_registered_specialists_have_expertise_packages(self):
        for name in SPECS:
            with self.subTest(name=name):
                package=load_package(name)
                self.assertEqual(package.name,name)
                self.assertEqual(package.max_depth,5)
                self.assertEqual(len(package.stages),6)
                self.assertIn("broad-to-specific",skill_context(name,depth=3))
                self.assertNotIn(package.stages[-1],
                                 package.disclose(1))

    def test_unauthorized_microtask_and_cycles_rejected(self):
        package=load_package("research")
        template={"version":1,"tasks":[{
            "id":"search_a","capability":"grounded_search",
            "depth":2,"depends_on":[],"arguments":{"query":"relevant evidence"}}]}
        approved=validate_program(template,package)
        self.assertEqual(len(approved),1)
        self.assertEqual(fingerprint(approved),fingerprint(approved))
        forbidden={"version":1,"tasks":[{
            "id":"attack","capability":"shell","depth":5,
            "depends_on":[],"arguments":{"command":"rm -rf /"}}]}
        with self.assertRaises(HACEContractError):
            validate_program(forbidden,package)
        cyclic={"version":1,"tasks":[{
            "id":"search_a","capability":"grounded_search",
            "depth":2,"depends_on":["search_a"],"arguments":{}}]}
        with self.assertRaises(HACEContractError):
            validate_program(cyclic,package)


class AdaptiveMicroprogram(unittest.IsolatedAsyncioTestCase):
    async def test_three_active_microtasks_and_dependency_barrier(self):
        package=load_package("research")
        raw={"version":1,"tasks":[
            {"id":f"search_{i}","capability":"grounded_search",
             "depth":2,"depends_on":[],"arguments":{"index":i}}
            for i in range(3)] + [
            {"id":"audit_all","capability":"claim_review","depth":5,
             "depends_on":["search_0","search_1","search_2"],
             "arguments":{"index":9}}]}
        tasks=validate_program(raw,package)
        started=asyncio.Event()
        released=asyncio.Event()
        active=0
        highest=0
        async def runner(arguments, predecessors):
            nonlocal active,highest
            if arguments["index"]==9:
                self.assertEqual(len(predecessors),3)
                return {"verified":True}
            active+=1
            highest=max(highest,active)
            if active==3:started.set()
            try:await released.wait()
            finally:active-=1
            return {"index":arguments["index"]}
        job=asyncio.create_task(execute_program(
            tasks,{"grounded_search":runner,"claim_review":runner},
            max_parallel=3))
        await asyncio.wait_for(started.wait(),2)
        self.assertFalse(job.done())
        released.set()
        result=await asyncio.wait_for(job,2)
        self.assertEqual(highest,3)
        self.assertEqual(result["audit_all"],{"verified":True})

    async def test_missing_handler_fails_closed(self):
        package=load_package("orchestrator")
        tasks=validate_program({"version":1,"tasks":[{
            "id":"compose_a","capability":"section_synthesis",
            "depth":3,"depends_on":[],"arguments":{}}]},package)
        with self.assertRaises(ExceptionGroup):
            await execute_program(tasks,{},max_parallel=3)

    async def test_editorial_hierarchy_produces_sections_without_slide_leakage(self):
        from rizzler.work_hace_editorial import synthesize_hierarchy
        draft={
            "audience":"Engineering reviewers",
            "core_question":"Production readiness of an agent execution system",
            "editorial_depth":"comprehensive",
            "sections":[
                {"heading":"System architecture","purpose":"Explain system mechanisms",
                 "evidence_or_assumptions":"Verified repository architecture facts",
                 "specific_analysis":"Compare runtime scheduling and durable state"},
                {"heading":"Failure recovery","purpose":"Explain reliable recovery",
                 "evidence_or_assumptions":"Observed service error taxonomy",
                 "specific_analysis":"Analyze retry invariants and edge cases"}
            ],
            "presentation_strategy":"Distill one meaningful conclusion per slide",
            "report_strategy":"Detailed evidence-aware technical explanation",
            "evidence_gaps":["No published load-test results available"]
        }
        async def fake_model(cfg,prompt,max_output_tokens):
            self.assertIn("System",prompt)
            await asyncio.sleep(0)
            return SimpleNamespace(text=(
                "The system implements bounded execution and maintains a "
                "persistent checkpoint for every committed specialist output. "
                "Source evidence must be attributed separately from assumptions. "
                "This section explains trade-offs, failure behavior and tests. "*3))
        with patch("rizzler.work_gemini_gateway.gemini_content",new=fake_model):
            result=await synthesize_hierarchy(
                "Write an in-depth technical analysis",draft,
                "System architecture uses persistent checkpoints.\n\n"
                "Failure recovery uses classified transient error codes.",
                [],None,object())
        self.assertIn("## System architecture",result)
        self.assertIn("## Failure recovery",result)
        self.assertNotIn("SLIDE 1:",result)


class ProceduralMemoryContracts(unittest.TestCase):
    def test_not_enabled_never_creates_store(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{
            "RIZZLER_MEMORY_ENABLED":"0","RIZZLER_LANGMEM_ENABLED":"1",
            "RIZZLER_MEMORY_ROOT":root,
            "RIZZLER_MEMORY_KEY":"some-independent-encryption-key-"+"x"*40}):
            self.assertIsNone(from_environment())
            self.assertEqual(list(Path(root).iterdir()),[])

    def test_only_bounded_categories_and_owner_hmac(self):
        with tempfile.TemporaryDirectory() as root:
            ledger=ProceduralLedger(root,"separate-memory-key-"+"x"*40)
            for _ in range(4):
                ledger.record("owner_alpha","research","quality_review_failed")
            batch=ledger.due()
            self.assertEqual(batch["signal_count"],4)
            self.assertEqual(batch["categories"]["quality_review_failed"],4)
            self.assertNotIn("owner_alpha",repr(batch))
            with self.assertRaises(ValueError):
                ledger.record("owner_alpha","research",
                              "sensitive user message with arbitrary contents")

    @unittest.skipUnless(importlib.util.find_spec("cryptography") is not None,
                         "Encrypted-memory dependency is optional in lean CI")
    def test_langmem_reflection_and_deletion_even_after_optout(self):
        from rizzler.work_langmem import reflect_once
        with tempfile.TemporaryDirectory() as root:
            key="independent-32-byte-encryption-key-"+"y"*40
            env={"RIZZLER_MEMORY_ENABLED":"1",
                 "RIZZLER_LANGMEM_ENABLED":"1",
                 "RIZZLER_MEMORY_ROOT":root,
                 "RIZZLER_MEMORY_KEY":key}
            with patch.dict(os.environ,env):
                ledger=from_environment()
                for _ in range(4):
                    ledger.record("owner_alpha","research","quality_review_failed")
                class MemoryManager:
                    async def ainvoke(self,request):
                        return [SimpleNamespace(content={
                            "specialist":"research",
                            "intervention":"Require source freshness and provenance before synthesizing analytical reports.",
                            "rationale":"Repeated independently classified review failures"})]
                def factory(*args,**kwargs):
                    return MemoryManager()
                result=asyncio.run(reflect_once(ledger,model=object(),factory=factory))
                self.assertEqual(result["status"],"hint_saved")
                self.assertTrue(ledger.guidance("owner_alpha","research"))
                self.assertEqual(ledger.guidance("owner_beta","research"),[])
                self.assertIsNone(ledger.due())
            with patch.dict(os.environ,dict(env,RIZZLER_LANGMEM_ENABLED="0")):
                delete_all_for_owner("owner_alpha")
            self.assertEqual(ledger.guidance("owner_alpha","research"),[])


if __name__=="__main__":
    unittest.main()
