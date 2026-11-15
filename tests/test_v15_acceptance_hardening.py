"""V15 acceptance regressions drawn from the failed 2026-11-15 Colab package.

All tests are isolated/offline; provider-backed and visual UX qualification
remain separate release gates.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase, skipUnless
from unittest.mock import AsyncMock, patch

from rizzler.work_dynamic import validate
from rizzler.work_finance import financial_profile
from rizzler.work_rich_docs import blocks, clean
from rizzler.work_presentation import complete_source_lineage


HEADERS=["Region","Product","Month","Units","Revenue_INR","Cost_INR","Gross_Profit_INR"]
ROWS=[
    ["North","Sensors","2025-01","10","1000","600","400"],
    ["South","Sensors","2025-01","12","1800","1100","700"],
    ["North","Controllers","2025-01","7","2100","900","1200"],
    ["South","Controllers","2025-01","9","2700","1600","1100"],
]
NARRATIVE=(
    "# Synthetic operations executive report\n\n"
    "## Executive summary\n"
    "Revenue is INR 7,600; cost is INR 4,200; gross profit is INR 3,400.\n\n"
    "## Regional comparisons\n"
    "| Region | Revenue INR | Gross profit INR |\n"
    "| --- | ---: | ---: |\n"
    "| North | 3100 | 1600 |\n"
    "| South | 4500 | 1800 |\n\n"
    "## Product comparisons\n"
    "| Product | Revenue INR | Gross profit INR |\n"
    "| --- | ---: | ---: |\n"
    "| Sensors | 2800 | 1100 |\n"
    "| Controllers | 4800 | 2300 |\n\n"
    "## Methodology and limitations\n"
    "All figures come from four synthetic source records; do not extrapolate.\n\n"
    "## Recommendations\n"
    "Review margin drivers by region and product without external assumptions."
)


def graph(research=False, all_formats=False):
    specs=[{"id":"sql_analytics","tool":"sql_analytics","depends_on":[],
            "thinking_level":"medium"}]
    if research:
        specs.append({"id":"research","tool":"research","depends_on":[],
                      "thinking_level":"medium"})
    deps=["sql_analytics"]+(["research"] if research else [])
    specs.append({"id":"orchestrator","tool":"orchestrator","depends_on":deps,
                  "thinking_level":"high"})
    names=(["powerpoint","word","excel","pdf_visual"] if all_formats else ["pdf_visual"])
    for name in names:
        predecessor=["orchestrator"]
        if name=="pdf_visual" and all_formats:
            predecessor+=["powerpoint","word","excel"]
        specs.append({"id":name,"tool":name,"depends_on":predecessor,
                      "thinking_level":"medium"})
    all_names=[step["id"] for step in specs]
    specs.append({"id":"quality","tool":"quality","depends_on":all_names,
                  "thinking_level":"medium"})
    return {"schema_version":2,"status":"ready","steps":specs}


class ScopeAndFinanceTests(TestCase):
    def test_uploaded_only_avoids_research_but_requires_narrative(self):
        payload={"objective":"Analyze only attached synthetic source records",
                 "deliverables":["md","data_analysis"],"uploads":["upload_id"],
                 "evidence_scope":"uploaded_only"}
        self.assertEqual(validate(graph(),payload)["status"],"ready")
        with self.assertRaisesRegex(ValueError,"forbids external research"):
            validate(graph(research=True),payload)

    def test_grouped_finance_reconciles_exact_source_rows(self):
        out=financial_profile(HEADERS,ROWS)
        self.assertEqual(out["currency"],"INR")
        self.assertEqual(out["total"]["revenue"],7600)
        self.assertEqual(out["total"]["cost"],4200)
        self.assertEqual(out["total"]["gross_profit"],3400)
        self.assertEqual(out["groups"]["Region"]["North"]["gross_profit"],1600)
        self.assertEqual(out["groups"]["Region"]["South"]["gross_profit"],1800)
        self.assertEqual(out["source_profit_rows_verified"],4)

    def test_source_mismatch_refuses_finance_publication(self):
        rows=[list(row) for row in ROWS]
        rows[0][-1]="999"
        with self.assertRaisesRegex(ValueError,"reconcile"):
            financial_profile(HEADERS,rows)

    def test_markdown_blocks_not_literal_text(self):
        parsed=blocks([("Main","### Regional results\n"
                       "| Group | Profit |\n| --- | --- |\n| North | 1600 |\n"
                       "- **Source-bound** comparison")])
        self.assertEqual([kind for kind,_ in parsed],
                         ["heading","heading","table","bullet"])
        self.assertEqual(clean("**Important**"),"Important")

    def test_pptx_source_lineage_covered_with_added_editable_source_slides(self):
        def slide(layout):
            return {"title":"Executive "+layout,"layout":layout,"headline":"",
                    "points":["Useful result"],"secondary":[],"metrics":[],
                    "citations":[],"notes":"Independent reviewer notes",
                    "chart_x":"","chart_y":""}
        story={"title":"Test presentation","slides":[slide("cover"),slide("bullets"),
                                                   slide("closing")]}
        sources=["https://official.example.org/report-"+str(i) for i in range(15)]
        result=complete_source_lineage(story,sources)
        self.assertEqual(set(sources),{c for s in result["slides"] for c in s["citations"]})
        self.assertGreaterEqual(len(result["slides"]),6)


@skipUnless(importlib.util.find_spec("docx") and importlib.util.find_spec("reportlab"),
            "Native document extras are not installed")
class RichArtifactTests(TestCase):
    def test_word_has_native_table_and_no_raw_markdown(self):
        from docx import Document
        from rizzler.work_rich_docs import render_docx
        with TemporaryDirectory() as root:
            path=Path(root)/"report.docx"
            render_docx(path,"Synthetic report",[("Summary",NARRATIVE)],None,
                        ["https://official.example.org/source"])
            doc=Document(path)
            self.assertGreaterEqual(len(doc.tables),2)
            text="\n".join(p.text for p in doc.paragraphs)
            self.assertNotIn("### ",text)
            self.assertNotIn("**",text)
            self.assertTrue(any(p.text=="Executive summary" for p in doc.paragraphs))
            self.assertTrue(any("official.example.org" in p.text for p in doc.paragraphs))

    def test_pdf_writes_native_tables_without_raw_google_redirects(self):
        from rizzler.work_rich_docs import render_pdf
        with TemporaryDirectory() as root:
            path=Path(root)/"report.pdf"
            render_pdf(path,"Synthetic report",[("Summary",NARRATIVE)],None,
                       ["https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"])
            self.assertGreater(path.stat().st_size,1200)
            if importlib.util.find_spec("fitz"):
                import fitz
                with fitz.open(path) as pdf:
                    text="\n".join(page.get_text() for page in pdf)
                    self.assertIn("Regional comparisons",text)
                    self.assertNotIn("grounding-api-redirect/abc",text)

    @skipUnless(importlib.util.find_spec("openpyxl"),"openpyxl unavailable")
    def test_finance_dashboard_and_independent_formula_contract(self):
        from rizzler.work_design import render_xlsx
        from rizzler.work_formula import verify_workbook
        from rizzler.work_skills import analyze
        from openpyxl import load_workbook
        with TemporaryDirectory() as root:
            path=Path(root)/"finance.xlsx"
            render_xlsx(path,"Finance",[("Summary","Source-only analysis")],
                        (HEADERS,ROWS),[])
            wb=load_workbook(path,read_only=True)
            try:
                self.assertIn("Financial Insights",wb.sheetnames)
                sheet=wb["Financial Insights"]
                self.assertEqual(sheet["B4"].value,7600)
                self.assertEqual(sheet["B6"].value,3400)
                self.assertEqual(sheet["B2"].value,"INR")
            finally:
                wb.close()
            report=verify_workbook(path,dataset_summary=analyze(HEADERS,ROWS))
            self.assertEqual(report["status"],"independently_verified")


@skipUnless(all(importlib.util.find_spec(x) for x in
                ("pptx","docx","reportlab","openpyxl")),
            "Optional renderer dependencies unavailable")
class FullOfflineBundle(IsolatedAsyncioTestCase):
    async def test_uploaded_only_job_completes_all_five_native_formats(self):
        from rizzler.work_store import WorkStore
        from rizzler.work_worker import WorkWorker
        from rizzler.work_skills import analyze
        from rizzler.work_quality import inspect_artifact
        from rizzler.work_presentation import validate_storyboard
        import csv
        storyboard={"title":"Synthetic executive briefing","slides":[{
            "title":title,"layout":layout,"headline":"Synthetic source only",
            "points":["Evidence-backed analysis of regions and products."],
            "secondary":[],"metrics":[],"citations":[],
            "notes":"No outside evidence was used.","chart_x":"","chart_y":""}
            for title,layout in (("Executive briefing","cover"),("Group comparisons","bullets"),
                                 ("Conclusion","closing"))]}
        async def composer(_objective, _summary):
            return NARRATIVE
        async def unexpected_research(_objective):
            raise AssertionError("External research must never run in uploaded-only mode")
        async def planner(_payload, _config):
            return graph(all_formats=True)
        with TemporaryDirectory() as root,\
             patch.dict(os.environ,{"RIZZLER_AGENTIC_ENABLED":"1",
                 "RIZZLER_ARTIFACT_QA":"structural",
                 "RIZZLER_V15_PRESENTATION":"1","RIZZLER_V15_RECOVERY":"0"}),\
             patch("rizzler.work_dynamic.generate",new=planner),\
             patch("rizzler.work_presentation.compose_storyboard",
                   new=AsyncMock(return_value=storyboard)):
            store=WorkStore(root)
            import io
            output=io.StringIO()
            writer=csv.writer(output)
            writer.writerow(HEADERS)
            writer.writerows(ROWS)
            upload=store.register_upload("owner_v15","synthetic.csv",output.getvalue().encode())
            job=store.submit("owner_v15","Build source-only financial comparison reports",
                    ["pptx","docx","xlsx","pdf","md","data_analysis"],
                    "acceptance_bundle_001",[upload["id"]],
                    evidence_scope="uploaded_only")
            from rizzler.work_specialists import execute_specialists
            worker_id="test_acceptance_worker"
            claimed=store.claim(worker_id,lease_seconds=120)
            await execute_specialists(store,claimed,worker_id,composer,unexpected_research)
            saved=store.get("owner_v15",job["id"])
            self.assertEqual(saved["status"],"completed",
                {"error":saved["error_code"],"agents":store.agent_steps("owner_v15",job["id"]),
                 "events":store.events("owner_v15",job["id"])})
            outputs=store.artifacts("owner_v15",job["id"])
            self.assertEqual(set(item["kind"] for item in outputs),
                             {"pptx","docx","xlsx","pdf","md"})
            for item in outputs:
                path,_=store.artifact("owner_v15",item["id"])
                self.assertTrue(path.stat().st_size>0)
            self.assertTrue(store.quality_report("owner_v15",job["id"])["quality"]["passed"])
