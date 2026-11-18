"""V23 E2E offline qualification: research synthesis and provider admission."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rizzler.cognitive_provider import ProviderSlots, _transient, generate_with_recovery
from rizzler.research_frontier import validate_frontier, investigation_prompt
from rizzler.work_store import WorkStore
from rizzler.work_worker import WorkWorker


class ResearchFrontierTests(unittest.TestCase):
    def test_dynamic_questions_and_invalid_schema(self):
        data = {"schema_version": 1, "investigations": [
            {"name": "Verify primary economic statistics",
             "question": "Which official source defines the reporting period and unit?",
             "evidence_needed": "Original statistical tables and a release date",
             "challenge": "Does an alternative agency use a conflicting definition?",
             "priority": 5},
            {"name": "Investigate independent interpretations",
             "question": "Which plausible explanations fit measured trade patterns?",
             "evidence_needed": "Independent series and documented methodologies",
             "challenge": "Could the same pattern arise from intermediate goods demand?",
             "priority": 2},
        ]}
        tasks = validate_frontier(data)
        self.assertEqual(tasks[0]["priority"], 5)
        self.assertIn("official source", investigation_prompt(tasks[0], "Trade analysis"))
        data["investigations"][1]["priority"] = 99
        with self.assertRaises(ValueError):
            validate_frontier(data)

    def test_research_to_synthesis_is_persisted_in_job_graph(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict("os.environ", {"RIZZLER_V23_UNIFIED_RESEARCH":"1"}, clear=False):
                store = WorkStore(Path(root) / "ledger")
                job = store.submit("owner_1", "Investigate source-supported design choices",
                                   ["research","md"],"v23_research_synthesis_001",[])
            graph = store.job_plan("owner_1",job["id"])
            lookup = {entry["id"]:entry for entry in graph["steps"]}
            self.assertIn("research",lookup["orchestrator"]["depends_on"])
            observed=[]
            async def research(objective):
                return {"text":"# Grounded findings\n\nThe supplied research question "
                        "has a documented methodology, distinct evidence and "
                        "uncertainty limitations for downstream synthesis.",
                        "sources":["https://example.org/research"]}
            async def composer(objective, metrics):
                observed.append(objective)
                return ("# Analytical synthesis\n\nOriginal findings have been "
                        "examined using source attribution and independent "
                        "methodological limitations. This report identifies "
                        "the limits of the available evidence.")
            self.assertTrue(asyncio.run(
                WorkWorker(store,composer=composer,researcher=research).once()))
            self.assertEqual(store.get("owner_1",job["id"])["status"],"completed")
            self.assertIn("Grounded findings",observed[0])
            completed={x["agent"] for x in store.agent_steps("owner_1",job["id"])
                       if x["status"]=="completed"}
            self.assertTrue({"research","orchestrator","pdf_visual","quality"} <= completed)


    def test_strict_evidence_blocks_unverified_provider_grounding(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict("os.environ",{
                "RIZZLER_V23_UNIFIED_RESEARCH":"1",
                "RIZZLER_CLAIM_VERIFY":"1"},clear=False):
                store=WorkStore(Path(root)/"work")
                job=store.submit("owner_1","Research official sources",
                                 ["research","md"],"evidence_required_job_001",[])
                async def researcher(objective):
                    return {"text":"# Findings\\nAttribution exists but no actual "
                            "retrieved passage is verified. This is not "
                            "enough for a formal evidence-backed report.",
                            "sources":["https://example.org/data"]}
                async def composer(objective,summary):
                    return "# Report\\nThis should never be published without evidence."
                asyncio.run(WorkWorker(
                    store,composer=composer,researcher=researcher).once())
            self.assertEqual(store.get("owner_1",job["id"])["status"],"failed")
            self.assertEqual(store.artifacts("owner_1",job["id"]),[])


class ProviderGovernorTests(unittest.TestCase):
    def test_slots_limit_independent_tasks(self):
        async def exercise(root):
            slots=ProviderSlots(root,capacity=2,ttl_seconds=30)
            active=[0];peak=[0]
            async def task():
                async with slots.acquire(wait_seconds=10):
                    active[0]+=1
                    peak[0]=max(peak[0],active[0])
                    await asyncio.sleep(.08)
                    active[0]-=1
            await asyncio.gather(*(task() for _ in range(5)))
            return peak[0],active[0]
        with tempfile.TemporaryDirectory() as tmp:
            peak,remaining=asyncio.run(exercise(tmp))
            self.assertEqual(peak,2)
            self.assertEqual(remaining,0)

    def test_retry_only_transient_provider_failures(self):
        class Error(Exception):
            def __init__(self,code):
                self.status_code=code
        self.assertTrue(_transient(Error(503)))
        self.assertTrue(_transient(Error(429)))
        self.assertFalse(_transient(Error(400)))

        class Model:
            def __init__(self): self.calls=0
            async def generate_content(self,**kwargs):
                self.calls+=1
                if self.calls==1:
                    raise Error(503)
                return {"success":True}
        class AIO:
            def __init__(self,model): self.models=model
        class Client:
            def __init__(self,model): self.aio=AIO(model)
        async def exercise():
            obj=Model()
            result=await generate_with_recovery(Client(obj),
                model="fake-model",contents="test",config=None,
                role="work",attempts=2,timeout=10)
            return obj.calls,result
        with tempfile.TemporaryDirectory() as root:
            with patch.dict("os.environ", {"RIZZLER_WORK_ROOT":root,
                                           "RIZZLER_PROVIDER_SLOTS":"2"},
                            clear=False):
                calls,result=asyncio.run(exercise())
        self.assertEqual(calls,2)
        self.assertEqual(result,{"success":True})


if __name__=="__main__":
    unittest.main()
