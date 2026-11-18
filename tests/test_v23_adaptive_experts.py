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
