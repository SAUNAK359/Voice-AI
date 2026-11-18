"""V23 HACE contracts, dependency scheduling and authorization regression."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rizzler.hace_runtime import (
    public_stage_summary, topological_waves, validate_stage_briefs)
from rizzler.task_planning import execution_graph


class HierarchicalRuntimeTests(unittest.TestCase):
    def test_existing_graph_is_scheduled_without_missing_dependencies(self):
        for formats, uploads in (
            (["pdf"], []),
            (["pptx", "docx", "pdf", "zip"], []),
            (["research", "pptx", "pdf"], []),
            (["data_analysis", "xlsx", "csv"], ["uploaded-fixture"]),
        ):
            graph = execution_graph({"deliverables": formats, "uploads": uploads,
                                     "objective": "Produce fully supported outputs"})
            approved = frozenset(node["id"] for node in graph["steps"])
            waves = topological_waves(graph, approved)
            self.assertEqual(set(sum((list(w) for w in waves), [])), approved)
            finished = set()
            lookup = {s["id"]: s for s in graph["steps"]}
            for wave in waves:
                for name in wave:
                    self.assertTrue(set(lookup[name]["depends_on"]) <= finished)
                finished.update(wave)
            self.assertEqual(waves[-1], ("quality",))

    def test_bad_graph_fails_closed(self):
        graph = execution_graph({"deliverables": ["pdf"], "uploads": [],
                                 "objective": "Render a PDF"})
        approved = frozenset(node["id"] for node in graph["steps"])
        graph["steps"][0]["tool"] = "web_search"
        with self.assertRaises(ValueError):
            topological_waves(graph, approved)

    def test_inverse_pyramid_contract_with_provenance(self):
        doc = {"schema_version": 23, "stages": [
            {"id": "general", "depth": 1, "parent": None,
             "specialist": "research", "objective": "Investigate the stated subject",
             "output_contract": "Source-backed research findings",
             "evidence_refs": []},
            {"id": "specific", "depth": 4, "parent": "general",
             "specialist": "quality", "objective": "Validate important factual claims",
             "output_contract": "Evidence-linked final QA decision",
             "evidence_refs": ["source-A"]},
        ]}
        result = validate_stage_briefs(
            doc, approved=frozenset({"research", "quality"}),
            evidence_ids=frozenset({"source-A"}))
        self.assertEqual(result[1].depth, 4)
        self.assertEqual(public_stage_summary(result)[1]["evidence_refs"], ["source-A"])
        doc["stages"][1]["evidence_refs"] = ["fabricated"]
        with self.assertRaises(ValueError):
            validate_stage_briefs(doc, approved=frozenset({"research", "quality"}),
                                  evidence_ids=frozenset({"source-A"}))

    def test_invalid_authority_or_hierarchy_rejected(self):
        root = {"id": "root", "depth": 1, "parent": None, "specialist": "quality",
                "objective": "Check the entire final outcome",
                "output_contract": "Report verified artifact quality",
                "evidence_refs": []}
        doc = {"schema_version": 23, "stages": [root]}
        self.assertEqual(len(validate_stage_briefs(
            doc, approved=frozenset({"quality"}))), 1)
        for key, value, error in (
            ("specialist", "deploy_production", PermissionError),
            ("parent", "missing", ValueError),
            ("depth", 9, ValueError),
            ("objective", "short", ValueError),
        ):
            bad = {"schema_version": 23, "stages": [{**root, key: value}]}
            with self.assertRaises(error):
                validate_stage_briefs(bad, approved=frozenset({"quality"}))
        with self.assertRaises(ValueError):
            validate_stage_briefs(doc, approved=frozenset({"quality", "research"}))


if __name__ == "__main__":
    unittest.main()
