"""V26 actual-file quantified claim gates: cross-format truth over self-review."""
from __future__ import annotations

from pathlib import Path
import sys
import importlib.util
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_context_fabric import node,create_fabric
from rizzler.work_consistency import (
    metric_catalog,validate_claim_report,reconcile_claim_reports,
    extracted_artifact_text,ConsistencyViolation)
from rizzler.work_studio import render_storyboard


def source_graph():
    return create_fabric(owner="the_owner",job_id="the_job",goal_digest="a"*64,
        nodes=[
            node(id="source:dataset",kind="source",status="attributed",
                 data={"url":"private://synthetic-csv",
                       "content_verified":False}),
            node(id="metric:net_total",kind="metric",status="computed_summary",
                 dependencies=["source:dataset"],
                 data={"name":"net_total","critical":True,
                       "value":-150,"unit":"synthetic_units",
                       "period":"Q1-Q4",
                       "source_table_sha256":"b"*64}),
            node(id="metric:import_total",kind="metric",status="computed_summary",
                 dependencies=["source:dataset"],
                 data={"name":"import_total","critical":True,
                       "value":600,"unit":"synthetic_units",
                       "period":"Q1-Q4",
                       "source_table_sha256":"b"*64})
        ])


def report(kind="pptx",claims=None):
    return {"schema_version":1,"artifact_kind":kind,
            "claims":claims if claims is not None else [],
            "assessment":"The reported numerals were checked against approved source computations."}


def claim(metric,value,excerpt):
    return {"metric_id":metric,"value":str(value),
            "unit":"synthetic_units","period":"Q1-Q4",
            "observed_excerpt":excerpt}


class ActualArtifactQuantitativeTests(unittest.TestCase):
    def setUp(self):
        self.graph=source_graph()
        self.catalog=metric_catalog(self.graph)

    def test_quality_auditor_uses_artifact_receipt_values_not_map_keys(self):
        """Regression: real Kaggle QA crashed on str.kind at quality stage."""
        import ast
        source=(Path(__file__).resolve().parents[1]/
                "src"/"rizzler"/"work_specialists.py").read_text(encoding="utf-8")
        tree=ast.parse(source)
        matches=[]
        for node in ast.walk(tree):
            if not isinstance(node,ast.ListComp):
                continue
            if not any(isinstance(t,ast.Attribute) and t.attr=="kind"
                       for t in ast.walk(node)):
                continue
            for generator in node.generators:
                iterator=generator.iter
                if (isinstance(iterator,ast.Call)
                        and isinstance(iterator.func,ast.Attribute)
                        and isinstance(iterator.func.value,ast.Name)
                        and iterator.func.value.id=="receipts"):
                    matches.append(iterator.func.attr)
        self.assertIn("values",matches,
                      "Cross-artifact quality must iterate real receipts, not strings")
        self.assertNotIn("keys",matches)

    def test_source_bound_metric_catalog(self):
        self.assertEqual(set(self.catalog),{
            "metric:net_total","metric:import_total"})
        self.assertEqual(self.catalog["metric:net_total"]["value"],"-150")

    def test_valid_observed_critical_claim(self):
        excerpt="The observed net trade position was -150 synthetic units."
        result=validate_claim_report(
            report(claims=[claim("metric:net_total",-150,excerpt)]),
            catalog=self.catalog,source_text=excerpt,kind="pptx")
        self.assertTrue(result["passed"])
        self.assertEqual(result["unobserved_critical_ids"],[
            "metric:import_total"])

    def test_reject_wrong_sum_even_when_model_calls_it_verified(self):
        excerpt="The net trade position was -145 synthetic units."
        with self.assertRaises(ConsistencyViolation):
            validate_claim_report(
                report(claims=[claim("metric:net_total",-145,excerpt)]),
                catalog=self.catalog,source_text=excerpt,kind="pptx")

    def test_reject_hallucinated_source_excerpt(self):
        with self.assertRaises(ConsistencyViolation):
            validate_claim_report(
                report(claims=[claim("metric:net_total",-150,
                    "Net deficit -150 synthetic units")]),
                catalog=self.catalog,
                source_text="Only the source totals were included.",
                kind="pptx")

    def test_reject_unauthorized_metric_identity(self):
        excerpt="Unverified profit reached 900 synthetic units."
        with self.assertRaises(ConsistencyViolation):
            validate_claim_report(
                report(claims=[claim("metric:profit",900,excerpt)]),
                catalog=self.catalog,source_text=excerpt,kind="pptx")

    def test_reject_changed_time_scope_and_currency(self):
        excerpt="Imports total 600 synthetic units."
        invalid=claim("metric:import_total",600,excerpt)
        invalid["period"]="2025"
        with self.assertRaises(ConsistencyViolation):
            validate_claim_report(
                report(claims=[invalid]),
                catalog=self.catalog,source_text=excerpt,kind="pptx")
        invalid["period"]="Q1-Q4"
        invalid["unit"]="USD"
        with self.assertRaises(ConsistencyViolation):
            validate_claim_report(
                report(claims=[invalid]),
                catalog=self.catalog,source_text=excerpt,kind="pptx")

    def test_missing_supported_artifacts_never_qualifies(self):
        result=reconcile_claim_reports({})
        self.assertFalse(result["passed"])

    @unittest.skipUnless(
        importlib.util.find_spec("docx") is not None,
        "Install the Work extra to test complete long-document inspection")
    def test_long_document_cannot_be_silently_truncated(self):
        from docx import Document
        from rizzler.work_consistency import MAX_SOURCE_CHARS
        with TemporaryDirectory() as temp:
            doc=Document()
            doc.add_paragraph("Important evidence " * (
                MAX_SOURCE_CHARS//15+50))
            source=Path(temp)/"extended.docx"
            doc.save(source)
            with self.assertRaisesRegex(
                    ConsistencyViolation,"complete-review budget"):
                extracted_artifact_text(source,"docx")

    def test_cross_format_critical_missing_fails_final_gate(self):
        net=validate_claim_report(
            report(claims=[claim("metric:net_total",-150,
                "Net deficit -150 synthetic units")]),
            catalog=self.catalog,
            source_text="Net deficit -150 synthetic units",kind="pptx")
        empty=validate_claim_report(
            report(kind="docx"),
            catalog=self.catalog,source_text="Unrelated executive report",
            kind="docx")
        joined=reconcile_claim_reports({"pptx":net,"docx":empty})
        self.assertFalse(joined["passed"])
        self.assertEqual(joined["missing_required_metrics"],[
            "metric:import_total"])
        imports=validate_claim_report(
            report(kind="docx",claims=[claim(
                "metric:import_total",600,
                "Imports total 600 synthetic units")]),
            catalog=self.catalog,
            source_text="Imports total 600 synthetic units",kind="docx")
        joined=reconcile_claim_reports({"pptx":net,"docx":imports})
        self.assertTrue(joined["passed"])

    @unittest.skipUnless(
        importlib.util.find_spec("pptx") is not None,
        "Install the work extra to exercise actual editable PowerPoint bytes")
    def test_actual_native_powerpoint_text_is_used(self):
        slides=[]
        for i in range(3):
            slides.append({
                "title":"Trade report for the period",
                "message":"Trade totals are source-computed for each observed quarter.",
                "kind":"takeaway",
                "bullets":[
                    "The observed net trade position was -150 synthetic units.",
                    "Imports total 600 synthetic units for the observed dataset."],
                "section_ids":[i],"source_urls":[]})
        blueprint={"schema_version":1,"slides":slides}
        with TemporaryDirectory() as root:
            path=Path(root)/"source.pptx"
            render_storyboard(
                path,blueprint,title="Trade analysis",
                sources=(),table=None)
            observed=extracted_artifact_text(path,"pptx")
            self.assertIn("-150",observed)
            self.assertIn("Imports total 600",observed)
            verified=validate_claim_report(
                report(claims=[
                    claim("metric:net_total",-150,
                        "The observed net trade position was -150 synthetic units."),
                    claim("metric:import_total",600,
                        "Imports total 600 synthetic units for the observed dataset.")
                ]),
                catalog=self.catalog,source_text=observed,kind="pptx")
            self.assertEqual(verified["unobserved_critical_ids"],[])


if __name__=="__main__":
    unittest.main()
