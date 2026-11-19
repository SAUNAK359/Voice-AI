"""Regression for failed Kaggle jobs: state, diagnostics and Excel contracts."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from rizzler.work_store import WorkStore, Missing
from rizzler.work_worker import WorkWorker
from rizzler.work_diagnostics import failure_code, failure_record


class LiveFailureRecoveryTests(TestCase):
    def test_full_mode_excel_has_no_unrequested_research(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict("os.environ",{"RIZZLER_V23_MODE":"full"},clear=True):
                store=WorkStore(Path(d)/"work")
                upload=store.register_upload(
                    "owner1","sales.csv",
                    b"region,revenue_inr,orders\nEast,100,2\nWest,200,4\n")
                job=store.submit("owner1","Analyze these sales figures and export Excel",
                    ["data_analysis","xlsx"],"full_excel_01",[upload["id"]])
                nodes={x["id"]:x for x in store.job_plan("owner1",job["id"])["steps"]}
                self.assertNotIn("research",nodes)
                self.assertEqual(nodes["orchestrator"]["depends_on"],["sql_analytics"])
                self.assertIn("excel",nodes)

    def test_research_contract_preserved_for_explicit_request(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict("os.environ",{"RIZZLER_V23_MODE":"full"},clear=True):
                store=WorkStore(Path(d)/"work")
                job=store.submit("owner1","Research a topic and create a report",
                    ["research","md"],"full_research_001",[])
            nodes={x["id"]:x for x in store.job_plan("owner1",job["id"])["steps"]}
            self.assertEqual(nodes["orchestrator"]["depends_on"],["research"])

    def test_failures_have_private_root_cause_and_no_prompt_leaks(self):
        marker="PRIVATE_USER_PROMPT_ABC123"
        async def failing(_objective,_summary):
            raise ValueError("malformed input "+marker)
        with tempfile.TemporaryDirectory() as d:
            with patch.dict("os.environ",{"RIZZLER_V23_MODE":"off"},clear=True):
                store=WorkStore(Path(d)/"work")
                job=store.submit("owner1","Create a simple report",
                                 ["md"],"diagnostic_job_01",[])
                self.assertTrue(asyncio.run(
                    WorkWorker(store,composer=failing).once()))
                result=store.get("owner1",job["id"])
                self.assertEqual(result["status"],"failed")
                errors=store.diagnostics("owner1",job["id"])
                self.assertGreaterEqual(len(errors),1)
                self.assertTrue(any(x["stage"]=="orchestrator" for x in errors))
                self.assertTrue(any(x["code"]=="contract_invalid" for x in errors))
                with self.assertRaises(Missing):
                    store.diagnostics("other",job["id"])
                with sqlite3.connect(store.db) as con:
                    text=" ".join(str(row) for row in con.execute(
                        "SELECT record_json FROM work_diagnostics"))
                self.assertNotIn(marker,text)
                self.assertNotIn("malformed input",text)

    def test_nested_taskgroup_root_error(self):
        exc=ExceptionGroup("tasks failed",[
            ValueError("raw credentials must not be persisted")])
        self.assertEqual(failure_code(exc),"contract_invalid")
        result=failure_record(exc,"orchestrator")
        self.assertEqual(result["exception_type"],"ValueError")
        self.assertNotIn("credentials",str(result))

    def test_cross_worker_model_rate_admission(self):
        from rizzler.cognitive_provider import ProviderSlots
        async def scenario(root):
            slots1=ProviderSlots(root,capacity=2,ttl_seconds=30)
            slots2=ProviderSlots(root,capacity=2,ttl_seconds=30)
            started=asyncio.get_running_loop().time()
            await asyncio.gather(
                slots1.admit_model_rate("gemini-test",rpm=2,
                                       window_seconds=.2,wait_seconds=2),
                slots2.admit_model_rate("gemini-test",rpm=2,
                                       window_seconds=.2,wait_seconds=2))
            first=asyncio.get_running_loop().time()-started
            await slots2.admit_model_rate("gemini-test",rpm=2,
                                          window_seconds=.2,wait_seconds=2)
            second=asyncio.get_running_loop().time()-started
            return first,second
        with tempfile.TemporaryDirectory() as d:
            first,second=asyncio.run(scenario(d))
        self.assertLess(first,.19)
        self.assertGreaterEqual(second,.16)

    def test_csv_signed_numbers_and_formula_injection(self):
        from rizzler.work_skills import csv_escape
        for value in ("-15.75", "+20", "-1.2e3", "0", "1.00"):
            self.assertEqual(csv_escape(value), value)
        for injection in ("=1+1", "+HYPERLINK('x')", "-SUM(A1:A2)",
                          "@SUM(A1:A2)", "\t=HYPERLINK('x')"):
            self.assertEqual(csv_escape(injection), "'" + injection)

    def test_structured_excel_no_category_aggregates(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("Excel Work extra not installed in minimal CI")
        from rizzler.work_excel_studio import (
            validate_workbook_plan,apply_workbook_plan,inspect_workbook_plan)
        from rizzler.work_skills import render_one
        plan={"schema_version":1,"analyses":[{
            "title":"Overall revenue measurement",
            "category":None,"measure":"revenue","aggregation":"mean",
            "rationale":"Compute observed mean without inventing a categorical column"}]}
        table=(["revenue"],[["10"],["20"],["30"]])
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"revenue.xlsx"
            render_one("xlsx",path,"Overall analysis",
                       "# Summary\nMeasurements from the supplied source.",table,[])
            approved=validate_workbook_plan(plan,table)
            apply_workbook_plan(path,approved)
            self.assertTrue(inspect_workbook_plan(path,approved)["passed"])
