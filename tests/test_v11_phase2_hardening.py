"""Phase 2 quality gates: meaningful report output, hostile input, repair, recovery."""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import unittest

if not all(importlib.util.find_spec(x) is not None for x in
           ("pytest", "fastapi", "httpx", "docx", "pptx", "openpyxl", "reportlab")):
    raise unittest.SkipTest("Phase 2 tests require App CI work/test extras")

import pytest

from rizzler.work_ir import compile_ir
from rizzler.work_skills import render_one
from rizzler.work_quality import inspect_artifact
from rizzler.work_formula import verify_workbook
from rizzler.work_visual import inspect_visual, quality_mode
from rizzler.work_store import WorkStore
from rizzler.work_worker import WorkWorker


TABLE = (["region","revenue","account_id"],
         [["North","10","0001"],["South","30","0002"],["West","20","0003"]])
TEXT = ("# Executive summary\nThe verified data contains three sales regions.\n"
        "## Findings\nThe sample has a mean revenue of 20 for three observations.")


def fixture():
    return compile_ir("Sales report", TEXT, ["https://example.org/report"],
                      {"rows":3,"columns":3,"duplicates":0,
                       "missing":{"region":0,"revenue":0,"account_id":0},
                       "numeric":{"revenue":{"count":3,"mean":20.0,"min":10.0,"max":30.0},
                                  "account_id":{"count":3,"mean":2.0,"min":1.0,"max":3.0}}})


def test_professional_formats_have_exact_source_and_editable_semantics(tmp_path):
    from docx import Document
    from pptx import Presentation
    from openpyxl import load_workbook
    ir = fixture()
    for kind in ("docx","pptx","xlsx","pdf"):
        target = tmp_path/("sales."+kind)
        render_one(kind,target,ir.title,ir.content,TABLE,list(ir.sources))
        report = inspect_artifact(target,kind,artifact_ir=ir,
                                  dataset_rows=3,dataset_summary={
                    "rows":3,"columns":3,"duplicates":0,
                    "missing":{"region":0,"revenue":0,"account_id":0},
                    "numeric":{"revenue":{"count":3,"mean":20.0,"min":10.0,"max":30.0},
                               "account_id":{"count":3,"mean":2.0,"min":1.0,"max":3.0}}})
        assert report["passed"],kind
    doc = Document(tmp_path/"sales.docx")
    assert len(doc.tables)>=1
    deck = Presentation(tmp_path/"sales.pptx")
    assert any(shape.has_chart for slide in deck.slides for shape in slide.shapes)
    wb = load_workbook(tmp_path/"sales.xlsx")
    assert {"Summary","Data","Checks","Dashboard","Sources"}.issubset(wb.sheetnames)
    assert wb["Data"]["C2"].value=="0001"
    assert wb["Data"]["B2"].value==10.0
    assert wb["Checks"]["C2"].value==3
    assert wb["Checks"]["B2"].value=="=ROWS(Data!A2:A4)"
    wb.close()


def test_source_and_body_tampering_fail_closed(tmp_path):
    from pptx import Presentation
    ir = fixture()
    deck = tmp_path/"a.pptx"
    render_one("pptx",deck,ir.title,ir.content,TABLE,list(ir.sources))
    p = Presentation(deck)
    for slide in p.slides:
        if slide.shapes.title and slide.shapes.title.text=="Findings":
            for shape in slide.shapes:
                if shape.has_text_frame and "mean revenue" in shape.text:
                    shape.text="Incorrect analysis substituted by attacker"
    p.save(deck)
    with pytest.raises(ValueError, match="IR"):
        inspect_artifact(deck,"pptx",artifact_ir=ir)
    from docx import Document
    doc = tmp_path/"a.docx"
    render_one("docx",doc,ir.title,ir.content,TABLE,list(ir.sources))
    d=Document(doc)
    for paragraph in d.paragraphs:
        if "mean revenue" in paragraph.text:
            paragraph.text="Different conclusion"
    d.save(doc)
    with pytest.raises(ValueError,match="IR"):
        inspect_artifact(doc,"docx",artifact_ir=ir)


def test_account_ids_never_become_numeric_and_formula_injection_is_neutralized(tmp_path):
    from openpyxl import load_workbook
    path=tmp_path/"test.xlsx"
    rows=(["account_id","amount","note"],
          [["0001","-10","=HYPERLINK(\"http://bad.test\")"],
           ["0002","20","+SUM(1,2)"]])
    render_one("xlsx",path,"Safety","# Evidence\nSafe data has been checked.",rows,[])
    wb=load_workbook(path)
    assert wb["Data"]["A2"].value=="0001"
    assert wb["Data"]["B2"].value==-10.0
    assert wb["Data"]["C2"].data_type!="f"
    assert wb["Data"]["C3"].data_type!="f"
    wb.close()
    assert verify_workbook(path)["formulas"]>=5


def test_independent_numeric_check_rejects_changed_formula_or_data(tmp_path):
    from openpyxl import load_workbook
    path=tmp_path/"bad.xlsx"
    render_one("xlsx",path,"Report","# Findings\nThree observations analyzed.",TABLE,[])
    wb=load_workbook(path)
    wb["Checks"]["B3"]="=AVERAGE(Data!B2:B10000)"
    wb.save(path)
    with pytest.raises(ValueError,match="formula"):
        verify_workbook(path)
    render_one("xlsx",path,"Report","# Findings\nThree observations analyzed.",TABLE,[])
    wb=load_workbook(path)
    wb["Data"]["B2"]=999
    wb.save(path)
    with pytest.raises(ValueError,match="calculation"):
        verify_workbook(path)


def test_strict_requires_real_qa_engine_no_fake_pass(monkeypatch,tmp_path):
    import rizzler.work_visual as visual
    monkeypatch.setenv("RIZZLER_ARTIFACT_QA","strict")
    assert quality_mode()=="strict"
    monkeypatch.setattr(visual.shutil,"which",lambda name:None)
    path=tmp_path/"deck.pptx"
    render_one("pptx",path,"Report",TEXT,None,[])
    with pytest.raises(RuntimeError):
        inspect_visual(path,"pptx",required=True)
    monkeypatch.setenv("RIZZLER_ARTIFACT_QA","bogus")
    with pytest.raises(ValueError,match="RIZZLER_ARTIFACT_QA"):
        quality_mode()


def test_worker_records_preflight_quality_and_strict_refuses_missing_render_engine(
        tmp_path,monkeypatch):
    async def composer(objective,metrics):
        return TEXT
    store=WorkStore(tmp_path/"work")
    job=store.submit("tester","Create an evidence-backed editable briefing",
                     ["docx","pptx","xlsx","pdf"],"qa_quality_001",[])
    assert asyncio.run(WorkWorker(store,composer=composer).once())
    done=store.get("tester",job["id"])
    assert done["status"]=="completed",done
    qa=store.quality_report("tester",job["id"])["quality"]
    assert qa["artifact_qa_mode"]=="structural"
    assert all(qa["artifact_quality"][kind]["passed"]
               for kind in ("docx","pptx","xlsx","pdf"))
    # Strict mode also accepts no synthetic/mock final success.
    monkeypatch.setenv("RIZZLER_ARTIFACT_QA","strict")
    import rizzler.work_visual as visual
    monkeypatch.setattr(visual.shutil,"which",lambda name:None)
    again=store.submit("tester","Create a second independently validated report",
                       ["docx"],"qa_quality_002",[])
    assert asyncio.run(WorkWorker(store,composer=composer).once())
    assert store.get("tester",again["id"])["status"]=="failed"
    assert store.artifacts("tester",again["id"])==[]


def test_single_bounded_deterministic_repair(tmp_path,monkeypatch):
    import rizzler.work_specialists as spec
    from rizzler.work_skills import render_one as original
    calls=[]
    def flaky(kind, path, title, content, table, sources):
        calls.append(kind)
        if kind=="md" and len(calls)==1:
            path.write_text("# broken",encoding="utf-8")
        else:
            return original(kind,path,title,content,table,sources)
    monkeypatch.setattr(spec,"render_one",flaky)
    async def composer(objective,metrics):return TEXT
    store=WorkStore(tmp_path/"work")
    job=store.submit("tester","Generate a report with recoverable formatting issue",
                     ["md"],"repair_quality_001",[])
    assert asyncio.run(WorkWorker(store,composer=composer).once())
    assert calls==["md","md"]
    assert store.get("tester",job["id"])["status"]=="completed"
    steps=store.agent_steps("tester",job["id"])
    stage=next(x for x in steps if x["agent"]=="pdf_visual")
    assert stage["status"]=="completed"
