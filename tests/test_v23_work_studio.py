"""Contract and end-to-end editable studio checks, no Gemini required."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rizzler.evidence_graph import evidence_index, validate_claims, claim_summary
from rizzler.work_studio import validate_storyboard, render_storyboard, inspect_storyboard
from rizzler.work_ir import compile_ir


class VerifiedEvidenceTests(unittest.TestCase):
    def test_source_byte_provenance_and_invented_quote_rejection(self):
        body = "In 2024 the reported trade total was 150 units, with the measurement based on historical data."
        source = {"source_id": "report_1", "sha256": hashlib.sha256(body.encode()).hexdigest(),
                  "source_url": "https://example.org/source", "blocks": [
                      {"type": "text", "text": body, "location": {"page": 3}}]}
        spans = evidence_index([source])
        self.assertEqual(len(spans), 1)
        eid = next(iter(spans))
        document = {"schema_version": 1, "claims": [{
            "claim": "The source reports a measured total of 150 units in 2024",
            "evidence_id": eid, "quote": "the reported trade total was 150 units",
            "interpretation": False, "limitations": "The source has not been fact-checked."}]}
        verified = validate_claims(document, spans)
        self.assertEqual(verified[0]["location"], {"page": 3})
        self.assertIn(eid, claim_summary(verified))
        document["claims"][0]["quote"] = "the total was actually 999 units"
        with self.assertRaises(ValueError):
            validate_claims(document, spans)
        document["claims"][0]["quote"] = "the reported trade total was 150 units"
        document["claims"][0]["evidence_id"] = "invented"
        with self.assertRaises(ValueError):
            validate_claims(document, spans)

    def test_untrusted_source_metadata_fails_closed(self):
        with self.assertRaises(ValueError):
            evidence_index([{"source_id": "../../file", "sha256": "0" * 64,
                             "blocks": [{"text": "A sufficiently long extract for indexing, which is fake."}]}])
        with self.assertRaises(ValueError):
            evidence_index([{"source_id": "valid", "sha256": "wrong",
                             "blocks": [{"text": "A sufficiently long extract for indexing, which is fake."}]}])


class AdaptiveStoryboardTests(unittest.TestCase):
    def _sample(self):
        ir = compile_ir("Trade dependency analysis",
            "# Context\nAn extensive, analytical overview of the measured problem and its limitations.\n"
            "## Evidence\nThe verified values are interpreted with explicit uncertainty and provenance.\n"
            "## Recommendations\nRecommendations are framed by measured uncertainty and stakeholder needs.",
            ["https://example.org/source"])
        slides = [
            {"title": "Executive trade dependency", "message": "The findings require careful source validation",
             "kind": "takeaway",
             "bullets": ["The report compares the major import categories.",
                         "Historical measurements require consistent definitions."],
             "section_ids": [0,1], "source_urls": ["https://example.org/source"]},
            {"title": "The evidence landscape", "message": "Data provenance determines the claim strength",
             "kind": "comparison",
             "bullets": ["Official source figures require consistent units.",
                         "Alternative explanations require independent review.",
                         "Year-to-year comparisons must preserve the same periods."],
             "section_ids": [1], "source_urls": ["https://example.org/source"]},
            {"title": "Defensible recommendations", "message": "Recommendations depend on validated baseline values",
             "kind": "decision",
             "bullets": ["Introduce reconciled data before making commitments.",
                         "Document remaining uncertainty and missing measurements."],
             "section_ids": [2], "source_urls": []},
        ]
        return ir, {"schema_version": 1, "slides": slides}

    def test_storyboard_validation_and_editable_render(self):
        try:
            import pptx
        except ImportError:
            self.skipTest("python-pptx work extra required")
        ir, blueprint = self._sample()
        valid = validate_storyboard(blueprint, ir.sections, ir.sources)
        self.assertEqual(valid["sections_covered"], [0,1,2])
        self.assertEqual(validate_storyboard(valid, ir.sections, ir.sources), valid)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "slides.pptx"
            render_storyboard(path, valid, title=ir.title, sources=ir.sources)
            audit = inspect_storyboard(path, valid)
            self.assertTrue(audit["passed"])
            self.assertEqual(audit["slides"], 3)
            deck = pptx.Presentation(path)
            self.assertGreater(len(deck.slides[1].shapes), 4)

    def test_storyboard_missing_section_and_invented_source_rejected(self):
        ir, blueprint = self._sample()
        blueprint["slides"][2]["section_ids"] = [1]
        with self.assertRaises(ValueError):
            validate_storyboard(blueprint, ir.sections, ir.sources)
        blueprint["slides"][2]["section_ids"] = [2]
        blueprint["slides"][0]["source_urls"] = ["https://unknown.example"]
        with self.assertRaises(ValueError):
            validate_storyboard(blueprint, ir.sections, ir.sources)


if __name__ == "__main__":
    unittest.main()
