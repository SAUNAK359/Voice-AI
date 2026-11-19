"""V23 stage-plan recovery, expert contract and cross-agent cognition tests."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rizzler.adaptive_experts import validate_expert_result, concise_expert_context
from rizzler.work_store import WorkStore, Missing


class DynamicExpertContracts(unittest.TestCase):
    def test_expert_citations_must_be_from_shared_evidence(self):
        found = {"finding": "This specialist considered the evidence, methods, "
                 "uncertainty, time periods and alternative explanations before "
                 "developing a recommendation for further verification.",
                 "method": "Compare original source periods before interpreting trends.",
                 "assumptions": ["The statistics use consistent reporting periods"],
                 "unresolved": ["Official definitions must be reconciled"],
                 "source_refs": ["https://example.org/report"]}
        allowed = frozenset({"https://example.org/report"})
        self.assertEqual(validate_expert_result(found, allowed)["proof_status"],
                         "source_attribution_only")
        found["source_refs"]=["https://attacker.invalid"]
        with self.assertRaises(ValueError):
            validate_expert_result(found, allowed)
        found["source_refs"]=[]
        self.assertEqual(validate_expert_result(found, allowed)["proof_status"],
                         "expert_analysis_unverified")

    def test_model_decomposition_survives_restarts_and_refuses_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkStore(Path(tmp) / "work")
            job = store.submit("owner_1", "Develop a complete report about evidence",
                               ["md"],"cognitive_plan_recovery_001",[])
            claim=store.claim("worker_1",45)
            fields = lambda ident, depth, parent, specialist: {
                "id":ident,"depth":depth,"parent":parent,"specialist":specialist,
                "objective":"A substantive focused task to validate important findings",
                "output_contract":"Produce a useful evidence-aware analytical result",
                "evidence_refs":[]}
            document = {"schema_version":23,"stages":[
                fields("root",1,None,"orchestrator"),
                fields("render",2,"root","pdf_visual"),
                fields("audit",3,"render","quality")]}
            digest=store.save_cognitive_plan(job["id"],"worker_1",claim["fence"],document)
            self.assertEqual(len(digest),64)
            reopened=WorkStore(Path(tmp)/"work")
            self.assertEqual(reopened.cognitive_plan("owner_1",job["id"]),document)
            with self.assertRaises(Missing):
                reopened.cognitive_plan("owner_2",job["id"])
            with sqlite3.connect(reopened.db) as db:
                db.execute("UPDATE cognitive_plans SET plan_json=? WHERE job_id=?",
                           ('{"schema_version":23,"stages":[]}',job["id"]))
            with self.assertRaises(ValueError):
                reopened.cognitive_plan("owner_1",job["id"])

    def test_sequential_experts_share_checkpointed_findings_and_reuse_after_restart(self):
        import asyncio
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        try:
            from google import genai
        except ImportError:
            self.skipTest("Live provider SDK extra not installed")
        from rizzler.adaptive_experts import run_expert_subtasks
        with tempfile.TemporaryDirectory() as tmp:
            store=WorkStore(Path(tmp)/"work")
            job=store.submit("owner_1","Produce a comprehensive technical report",
                             ["md"],"expert_cognition_test_001",[])
            claim=store.claim("worker_1",45)
            fields=lambda ident,depth,parent,specialist: {
                "id":ident,"depth":depth,"parent":parent,"specialist":specialist,
                "objective":"Investigate a domain-specific evidence uncertainty",
                "output_contract":"Prepare complete technical findings and limitations",
                "evidence_refs":[]}
            plan={"schema_version":23,"stages":[
                fields("root",1,None,"orchestrator"),
                fields("evidence",2,"root","pdf_visual"),
                fields("audit",3,"evidence","quality")]}
            prompts=[]
            async def fake_generate(client,*,contents,**kwargs):
                prompts.append(contents)
                return SimpleNamespace(text=json.dumps({
                    "finding":"This expert identifies the principal assumptions, "
                              "the available evidence, concrete methods and a "
                              "decision strategy that must be independently tested.",
                    "method":"Validate inputs and evaluate competing technical interpretations.",
                    "assumptions":["Input measurements describe comparable cases"],
                    "unresolved":["A secondary reference has not been obtained"],
                    "source_refs":[]}))
            aio=SimpleNamespace(aclose=lambda:asyncio.sleep(0))
            fake_client=SimpleNamespace(aio=aio)
            with patch.object(genai,"Client",return_value=fake_client), patch(
                    "rizzler.cognitive_provider.generate_with_recovery",
                    side_effect=fake_generate):
                first=asyncio.run(run_expert_subtasks(
                    store,claim,"worker_1",plan,
                    objective="Produce a comprehensive technical report",
                    sources=[],evidence="No independently verified source supplied",
                    model="mock",api_key="mock",parallelism=1))
                second=asyncio.run(run_expert_subtasks(
                    store,claim,"worker_1",plan,
                    objective="Produce a comprehensive technical report",
                    sources=[],evidence="No independently verified source supplied",
                    model="mock",api_key="mock",parallelism=1))
            self.assertEqual(first["executed"],2)
            self.assertEqual(second["cached"],2)
            self.assertEqual(len(prompts),2)
            self.assertIn("Completed sibling findings",prompts[1])
            self.assertEqual(len([e for e in store.cognitive_events("owner_1",job["id"])
                                  if e["agent"]=="domain_expert"]),2)

    def test_invalid_advisory_expert_is_quarantined_without_blocking_valid_sibling(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch
        try:
            from google import genai
        except ImportError:
            self.skipTest("Live provider SDK extra not installed")
        from rizzler.adaptive_experts import run_expert_subtasks
        with tempfile.TemporaryDirectory() as tmp:
            store=WorkStore(Path(tmp)/"work")
            job=store.submit("owner_1","Develop a documented technical report",
                             ["md"],"expert_quarantine_test_001",[])
            claim=store.claim("worker_1",45)
            def field(identifier,depth,parent,specialist):
                return {"id":identifier,"depth":depth,"parent":parent,
                        "specialist":specialist,
                        "objective":"Investigate a clearly bounded methodology",
                        "output_contract":"Return source-aware documented findings",
                        "evidence_refs":[]}
            stages={"schema_version":23,"stages":[
                field("root",1,None,"orchestrator"),
                field("weak",2,"root","pdf_visual"),
                field("valid",3,"weak","quality")]}
            seen={}
            async def generate(client,*,contents,**kwargs):
                key="weak" if '"id": "weak"' in contents else "valid"
                seen[key]=seen.get(key,0)+1
                if key=="weak":
                    return SimpleNamespace(text=json.dumps({
                        "finding":"Too short","method":"Short",
                        "assumptions":[],"unresolved":[],"source_refs":[]}))
                return SimpleNamespace(text=json.dumps({
                    "finding":"The evidence and methodology have to be "
                              "validated independently before any claims are "
                              "advanced for publication or technical adoption.",
                    "method":"Compare inputs, controls and alternative explanations.",
                    "assumptions":[],"unresolved":["Original source checks pending"],
                    "source_refs":[]}))
            aio=SimpleNamespace(aclose=lambda:asyncio.sleep(0))
            with patch.object(genai,"Client",return_value=SimpleNamespace(aio=aio)),patch(
                    "rizzler.cognitive_provider.generate_with_recovery",
                    side_effect=generate):
                outcome=asyncio.run(run_expert_subtasks(
                    store,claim,"worker_1",stages,
                    objective="Develop a documented technical report",
                    sources=[],evidence="",model="mock",api_key="mock"))
            self.assertEqual(outcome["rejected"],1)
            self.assertEqual(outcome["executed"],1)
            self.assertEqual(len(outcome["results"]),1)
            self.assertEqual(seen["weak"],3)
            ledger=store.cognitive_events("owner_1",job["id"])
            self.assertEqual(len([v for v in ledger
                if v["agent"]=="domain_expert" and v["kind"]=="finding"]),1)
            self.assertEqual(len([v for v in ledger
                if v["agent"]=="domain_expert" and v["kind"]=="gap"]),1)

    def test_public_expert_context_preserves_uncertainty(self):
        result = {"results":[{"task_id":"trade_economics",
            "result":{"finding":"The sampled evidence suggests different outcomes",
                      "method":"Compare measured periods",
                      "unresolved":["Missing original data"],
                      "source_refs":["https://example.org/data"]}}]}
        summary=concise_expert_context(result)
        self.assertIn("Missing original data", summary)
        self.assertIn("trade_economics", summary)


if __name__=="__main__":
    unittest.main()
