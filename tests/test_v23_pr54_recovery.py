"""Offline regressions for word content recovery and focus-first quote evidence."""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rizzler.work_editor import merge_editorial_expansions, validate_report_plan
from rizzler.research_intelligence import validate_passage_order
from rizzler.evidence_graph import evidence_brief


class EditorialRecoveryTests(unittest.TestCase):
    def _draft(self):
        return {"schema_version": 1, "medium": "docx", "sections": [
            {"heading": "Methods and evaluation", "body": "Methods need evidence. " * 29,
             "section_ids": [0], "source_urls": []},
            {"heading": "Evidence limitations", "body": "Explain uncertainty carefully. " * 24,
             "section_ids": [1], "source_urls": []},
            {"heading": "Operational implications", "body": "Implications need caution. " * 28,
             "section_ids": [2], "source_urls": []}]}

    def test_targeted_expansion_preserves_original_and_repairs_shortage(self):
        draft=self._draft()
        original=[x["body"] for x in draft["sections"]]
        supplement="Independent confirmation requires datasets, a defined evaluation protocol and a documented failure model. " * 9
        additions={"expansions":[{"index":i,"supplement":supplement} for i in range(3)]}
        result=merge_editorial_expansions(draft,additions,allowed_sources=())
        for old, item in zip(original,result["sections"]):
            self.assertTrue(item["body"].startswith(old.rstrip()))
        plan=validate_report_plan(result,medium="docx",
            original_sections=(("Methods", "Original method."),
                               ("Limitations", "Original limitation."),
                               ("Implications", "Original implication.")),
            allowed_sources=())
        self.assertGreaterEqual(plan["word_count"],450)

    def test_untrusted_url_and_invalid_section_rejected(self):
        draft=self._draft()
        for additions in (
            {"expansions":[{"index":9,"supplement":"A"*140}]},
            {"expansions":[{"index":0,"supplement":"https://unapproved.example/ " + "A"*160}]},
            {"expansions":[{"index":0,"supplement":"A"*160},
                           {"index":0,"supplement":"B"*160}]}
        ):
            with self.subTest(additions=additions),self.assertRaises(ValueError):
                merge_editorial_expansions(draft,additions,allowed_sources=())

class EvidenceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.spans={
            "a":{"source_id":"tutorial","source_url":"https://tutorial.example/",
                 "location":{"page":1},"text":"An agency compiles trade statistics."*5},
            "b":{"source_id":"government","source_url":"https://official.example/",
                 "location":{"page":3},"text":"Export value was 500 billion INR in 2025 and import value was 700 billion INR."*3}
        }

    def test_restricts_rankings_to_original_byte_backed_ids(self):
        self.assertEqual(validate_passage_order({"prioritized_ids":["b","a"]},self.spans),["b","a"])
        for value in ([],["missing"],["a","a"],["a",12]):
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate_passage_order({"prioritized_ids":value},self.spans)

    def test_selected_passage_is_full_original_not_model_preview(self):
        selected={k:self.spans[k] for k in ["b"]}
        result=evidence_brief(selected)
        self.assertIn("Export value was 500 billion INR",result)
        self.assertNotIn("An agency compiles trade statistics",result)


if __name__ == "__main__":
    unittest.main()
