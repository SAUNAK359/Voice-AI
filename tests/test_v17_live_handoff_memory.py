"""Native Live/Work memory capability isolation and policy contracts."""
import unittest
from rizzler.live_schema import validate_call, public_schema


class NativeLiveMemoryContractTests(unittest.TestCase):
    def test_recall_has_strict_bounded_query(self):
        self.assertEqual(validate_call("memory_recall",{"query":"client reporting preferences"}),{
            "query":"client reporting preferences"})
        with self.assertRaises(ValueError):
            validate_call("memory_recall",{"query":"x"*601})
        with self.assertRaises(ValueError):
            validate_call("memory_recall",{"query":"ok","owner":"other_user"})
        with self.assertRaises(ValueError):
            validate_call("memory_recall",{"query":"user preference"},enabled=False)

    def test_live_contract_exposes_explicit_research_scope(self):
        call={"objective":"Research recent market data and create PowerPoint",
              "deliverables":["pptx","pdf"],
              "source_coverage":"targeted",
              "evidence_scope":"external_allowed"}
        self.assertEqual(validate_call("work_submit",call),call)
        with self.assertRaises(ValueError):
            validate_call("work_submit",dict(call,evidence_scope="unrestricted"))
        self.assertIn("evidence_scope",public_schema("work_submit")["properties"])
