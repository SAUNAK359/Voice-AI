"""V26 decision-oriented, editable Excel dashboard over real analytical proof.

The model selects a meaningful method upstream. This module uses original
Data columns for formulas, not model-authored numbers, and independently
checks its source receipt, KPI values, formula references, and native charts.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

class DashboardContractError(ValueError):
    """Missing source, changed analytical result, or workbook formula mismatch."""


def _verified(table,receipt):
    from .work_reasoning_audit import execute_comparison
    if not isinstance(receipt,dict) or receipt.get("schema_version")!=2:
        raise DashboardContractError("Missing verified analytical method")
    plan={
        "schema_version":2,
        "category_column":receipt["category_column"],
        "first_measure":receipt["first_measure"],
        "second_measure":receipt["second_measure"],
        "aggregation":receipt["aggregation"],
        "measurement_unit":receipt["measurement_unit"],
        "analytical_question":"Validate analytical comparison over original source",
        "confounder_columns":[],
    }
    computed=execute_comparison(plan,table)
    if (computed["source_sha256"]!=receipt["source_sha256"] or
            computed["groups"]!=receipt["groups"] or
            computed["total_difference"]!=receipt["total_difference"]):
        raise DashboardContractError("Model or workbook changed the source computations")
    if not 1<=len(computed["groups"])<=256:
        raise DashboardContractError("Dashboard category budget exceeded")
    return plan,computed


def _positions(table,plan):
    from openpyxl.utils import get_column_letter
    names=list(table[0])
    return (
        get_column_letter(names.index(plan["category_column"])+1),
        get_column_letter(names.index(plan["first_measure"])+1),
        get_column_letter(names.index(plan["second_measure"])+1),
        len(table[1])+1,
    )


def _range(col,last):
    return "Data!"+col+"$2:"+col+"$"+str(last)


def _formula(agg,group_col,measure_col,last,row):
    name="SUMIF" if agg=="sum" else "AVERAGEIF"
    return "="+name+"("+_range(group_col,last)+",A"+str(row)+","+
        _range(measure_col,last)+")"


def apply_source_dashboard(path: Path,table,receipt: dict) -> dict:
    from openpyxl import load_workbook
    from openpyxl.styles import Font,PatternFill,Alignment
    from openpyxl.chart import BarChart,LineChart,Reference
    plan,proof=_verified(table,receipt)
    cat,a,b,end=_positions(table,plan)
    wb=load_workbook(path)
    try:
        if "Decision Dashboard" in wb.sheetnames:
            raise DashboardContractError("Duplicate analytical dashboard")
        if "Data" not in wb:
            raise DashboardContractError("Missing original Data sheet")
        wsdata=wb["Data"]
        headers=[cell.value for cell in wsdata[1]]
        if headers!=list(table[0]) or wsdata.max_row!=end:
            raise DashboardContractError("Source workbook differs from original dataset")
        ws=wb.create_sheet("Decision Dashboard",1)
        ws.merge_cells("A1:H1")
        ws["A1"]="SOURCE-BOUND DECISION DASHBOARD"
        ws["A1"].font=Font(size=18,bold=True,color="173A55")
        ws.merge_cells("A2:H2")
        ws["A2"]="Source computations, editable formulas, no fabricated assumptions"
        ws.merge_cells("A3:H3")
        ws["A3"]="Units: "+proof["measurement_unit"]+" | Category: "+plan["category_column"]
        ws["A3"].font=Font(color="9A542B",bold=True)
        for letter in "ABCDEFGH":
            ws.column_dimensions[letter].width=28 if letter=="A" else 20
        ws["A5"]="TOTAL "+plan["first_measure"]
        ws["B5"]="=SUM("+_range(a,end)+")"
        ws["D5"]="TOTAL "+plan["second_measure"]
        ws["E5"]="=SUM("+_range(b,end)+")"
        ws["G5"]="NET SECOND − FIRST"
        ws["H5"]="=E5-B5"
        for cell in ("B5","E5","H5"):
            ws[cell].font=Font(size=16,bold=True,color="087A75")
        for idx,heading in enumerate(
                ("Category",plan["first_measure"],
                 plan["second_measure"],"Difference"),1):
            cell=ws.cell(8,idx,heading)
            cell.fill=PatternFill("solid",fgColor="173A55")
            cell.font=Font(color="FFFFFF",bold=True)
        audit=wb.create_sheet("Dashboard Audit")
        audit.append(["Category","Source first","Source second",
                      "Source difference"])
        for i,item in enumerate(proof["groups"],9):
            ws.cell(i,1,item["category"])
            ws.cell(i,2,_formula(plan["aggregation"],cat,a,end,i))
            ws.cell(i,3,_formula(plan["aggregation"],cat,b,end,i))
            ws.cell(i,4,"=C"+str(i)+"-B"+str(i))
            audit.append([
                item["category"],float(item["first"]),
                float(item["second"]),float(item["difference"])])
        audit.append(["Source SHA-256",proof["source_sha256"]])
        audit.append(["Original unit",proof["measurement_unit"]])
        ws.freeze_panes="A9"
        finish=8+len(proof["groups"])
        ws.auto_filter.ref="A8:D"+str(finish)
        categories=Reference(ws,min_col=1,min_row=9,max_row=finish)
        dual=BarChart()
        dual.title="Comparison by "+plan["category_column"]
        dual.y_axis.title=proof["measurement_unit"]
        dual.add_data(Reference(
            ws,min_col=2,max_col=3,min_row=8,max_row=finish),
            titles_from_data=True)
        dual.set_categories(categories)
        dual.width,dual.height=16,8
        ws.add_chart(dual,"F9")
        difference=LineChart()
        difference.title="Observed difference (second − first)"
        difference.y_axis.title=proof["measurement_unit"]
        difference.add_data(Reference(
            ws,min_col=4,min_row=8,max_row=finish),
            titles_from_data=True)
        difference.set_categories(categories)
        difference.width,difference.height=16,8
        ws.add_chart(difference,"F27")
        start=max(finish+3,50)
        ws.cell(start,1,"RESEARCH AND INTERPRETATION LIMITS")
        for idx,warning in enumerate(proof["epistemic_limitations"],start+1):
            ws.merge_cells(start_row=idx,start_column=1,
                           end_row=idx,end_column=8)
            cell=ws.cell(idx,1,warning)
            cell.alignment=Alignment(wrap_text=True)
            ws.row_dimensions[idx].height=34
        wb.calculation.fullCalcOnLoad=True
        wb.calculation.forceFullCalc=True
        wb.save(path)
    finally:
        wb.close()
    return inspect_source_dashboard(path,table,receipt)


def inspect_source_dashboard(path: Path,table,receipt: dict) -> dict:
    from openpyxl import load_workbook
    plan,proof=_verified(table,receipt)
    cat,a,b,end=_positions(table,plan)
    wb=load_workbook(path,data_only=False,read_only=False)
    try:
        if not {"Data","Decision Dashboard","Dashboard Audit"}<=set(wb.sheetnames):
            raise DashboardContractError("Missing required workbook sheets")
        ws=wb["Decision Dashboard"]
        audit=wb["Dashboard Audit"]
        expected={
            "B5":"=SUM("+_range(a,end)+")",
            "E5":"=SUM("+_range(b,end)+")",
            "H5":"=E5-B5",
        }
        if any(ws[k].value!=v for k,v in expected.items()):
            raise DashboardContractError("Workbook KPI formula changed")
        for idx,item in enumerate(proof["groups"],9):
            if (ws.cell(idx,1).value!=item["category"]
                    or ws.cell(idx,2).value!=_formula(
                        plan["aggregation"],cat,a,end,idx)
                    or ws.cell(idx,3).value!=_formula(
                        plan["aggregation"],cat,b,end,idx)
                    or ws.cell(idx,4).value!="=C"+str(idx)+"-B"+str(idx)):
                raise DashboardContractError("Source-linked comparison formulas changed")
            row=idx-7
            for col,key in ((2,"first"),(3,"second"),(4,"difference")):
                if Decimal(str(audit.cell(row,col).value))!=Decimal(item[key]):
                    raise DashboardContractError("Independent numeric proof differs")
        if len(ws._charts)!=2:
            raise DashboardContractError("Missing editable source charts")
        if proof["measurement_unit"] not in (ws["A3"].value or ""):
            raise DashboardContractError("Missing source unit uncertainty")
        return {"passed":True,"source_sha256":proof["source_sha256"],
                "category_count":len(proof["groups"]),
                "editable_chart_count":len(ws._charts),
                "total_difference":proof["total_difference"],
                "checks":["actual_source_formula","independent_decimal_oracle",
                          "unit_disclosure","native_editable_charts"]}
    finally:
        wb.close()
