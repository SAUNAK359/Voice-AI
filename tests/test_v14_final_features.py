"""Acceptance tests for V14 interactive data, model reasoning, and versioned repair."""
import asyncio
import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from rizzler.dashboard_data import data
from rizzler.work_reasoning import current,use
from rizzler.work_dynamic import validate
from rizzler.work_ir import compile_ir

class InteractiveDashboardTests(unittest.TestCase):
    def test_csv_is_real_editable_data_not_synthetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"metrics.csv"
            with path.open("w",newline="",encoding="utf-8") as output:
                w=csv.writer(output)
                w.writerow(["Supplier","Orders","Delay Days"])
                w.writerow(["Acme",120,3]);w.writerow(["Bravo",70,9])
            result=data(path,"csv")
            self.assertEqual(result["source_rows"],2)
            self.assertEqual(result["columns"],["Supplier","Orders","Delay Days"])
            self.assertEqual(result["rows"][1],["Bravo","70","9"])
            with self.assertRaises(ValueError):data(path,"pdf")
    def test_xlsx_sheets_can_be_selected(self):
        try:from openpyxl import Workbook
        except ImportError:self.skipTest("openpyxl optional")
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"dashboard.xlsx"
            wb=Workbook();ws=wb.active;ws.title="Data"
            ws.append(["Team","Revenue"]);ws.append(["North",42])
            other=wb.create_sheet("Forecast");other.append(["Month","Expected"]);other.append(["Jan",50]);wb.save(p)
            result=data(p,"xlsx")
            self.assertEqual(result["rows"],[["North","42"]])
            self.assertEqual(data(p,"xlsx","Forecast")["rows"],[["Jan","50"]])
            with self.assertRaises(ValueError):data(p,"xlsx","Unowned")

class AdaptiveReasoningTests(unittest.TestCase):
    def test_thinking_context_restores_across_calls(self):
        self.assertEqual(current(),"medium")
        with use("high"):
            self.assertEqual(current(),"high")
            with use("medium"):self.assertEqual(current(),"medium")
            self.assertEqual(current(),"high")
        self.assertEqual(current(),"medium")
        with self.assertRaises(ValueError):
            with use("extreme"):pass
    def test_model_graph_choose_medium_high_without_keyword_routing(self):
        payload={"objective":"Make a summary","deliverables":["md"],"uploads":[]}
        def graph(level):
            return {"schema_version":2,"status":"ready","steps":[
                {"id":"orchestrator","tool":"orchestrator","depends_on":[],"thinking_level":level},
                {"id":"pdf_visual","tool":"pdf_visual","depends_on":["orchestrator"],"thinking_level":"high"},
                {"id":"quality","tool":"quality","depends_on":["orchestrator","pdf_visual"],"thinking_level":"high"}]}
        self.assertEqual(validate(graph("medium"),payload)["steps"][0]["thinking_level"],"medium")
        self.assertEqual(validate(graph("high"),payload)["steps"][0]["thinking_level"],"high")
        with self.assertRaises(ValueError):validate(graph("extreme"),payload)

class RepairLoopTests(unittest.IsolatedAsyncioTestCase):
    def build(self):
        original=compile_ir("Supply chain report","# Results\nWarehouse performance improved.",[],None)
        record={"artifact_ir":original,"text":original.content,"summary":None,
                "receipts":{"md":SimpleNamespace(kind="md",name="md.md",sha256="0"*64)},
                "sources":[],"source_coverage":None}
        payload={"objective":"Explain supplier risk","deliverables":["md"]}
        return record,payload
    async def test_model_repairs_then_revalidates(self):
        from rizzler.work_repair import validate_repair
        record,payload=self.build();count=[0]
        async def check(*args,**kwargs):
            count[0]+=1
            return ({},[{"kind":"md","problem":"Needs stronger explanation"}]) if count[0]==1 else ({"md":{"passed":True}},[])
        revised=compile_ir("Supply chain report","# Results\nWarehouse performance improved and supplier delays were documented.",[],None)
        async def rebuild(store,claim,worker,checkpoint,context,payload,iteration,ir):
            context["artifact_ir"]=ir;context["text"]=ir.content
            return {"revision":iteration,"prior_ir_sha256":"old","current_ir_sha256":ir.sha256}
        with patch("rizzler.work_repair._verify_bundle",new=check),\
             patch("rizzler.work_repair._revision",new=AsyncMock(return_value=revised)),\
             patch("rizzler.work_repair._rebuild",new=rebuild),\
             patch("rizzler.work_repair.quality_mode",return_value="agentic"):
            outcome=await validate_repair(None,{"owner":"owner","id":"job","fence":1},
                                           "worker",Path("/tmp"),record,payload)
        self.assertTrue(outcome["passed"])
        self.assertEqual(outcome["revision_count"],1)
        self.assertEqual(count[0],2)
        self.assertEqual(record["artifact_ir"].sha256,revised.sha256)
    async def test_unresolved_defect_is_not_published(self):
        from rizzler.work_repair import validate_repair
        record,payload=self.build()
        async def check(*args):return {},[{"kind":"md","problem":"Unresolved defect"}]
        async def rebuild(store,claim,worker,checkpoint,context,payload,iteration,ir):
            context["artifact_ir"]=ir;return {"revision":iteration}
        with patch("rizzler.work_repair._verify_bundle",new=check),\
             patch("rizzler.work_repair._revision",new=AsyncMock(return_value=record["artifact_ir"])),\
             patch("rizzler.work_repair._rebuild",new=rebuild),\
             patch("rizzler.work_repair.quality_mode",return_value="agentic"):
            with self.assertRaisesRegex(ValueError,"failed QA"):
                await validate_repair(None,{"owner":"owner","id":"job","fence":1},
                                      "worker",Path("/tmp"),record,payload)

if __name__=="__main__":unittest.main()
