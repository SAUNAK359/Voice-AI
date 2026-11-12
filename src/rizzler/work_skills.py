"""Explicit, dependency-light Work Agent skills.

Never invent citations, analytics or data. Non-grounded research is rejected.
The 17-skill catalog is an interface, not a claim of 17 verified live skills.
"""
from __future__ import annotations

import csv
import html
import io
import json
import math
import re
from collections import Counter
from pathlib import Path

SKILLS = {
    "research": "Grounded synthesis only with provider-grounded URL metadata",
    "data_analysis": "Deterministic descriptive CSV/XLSX metrics",
    "pdf": "Editable-source-derived PDF document",
    "docx": "Word document",
    "pptx": "Editable PowerPoint presentation",
    "xlsx": "Analytical workbook",
    "csv": "Interoperable data table",
    "json": "Machine-readable report",
    "md": "Markdown report",
    "html": "Standalone HTML report",
    "png": "Dataset-backed visualization or text summary",
    "svg": "Vector visualization",
    "txt": "Text briefing",
    "zip": "SHA-256 release bundle",
    "automation_plan": "Human approval proposal (no automatic scheduling)",
    "task_management": "Durable state, lease and progress events",
    "voice_status": "Spoken summary grounded in persisted state",
}
FORMATS = {"pdf","docx","pptx","xlsx","csv","json","md","html","png","svg","txt","zip"}


def read_dataset(path: Path) -> tuple[list[str], list[list[str]]]:
    path = Path(path)
    if path.suffix.lower()==".csv":
        with path.open("r",encoding="utf-8-sig",newline="") as f:
            table=list(csv.reader(f))
    elif path.suffix.lower()==".xlsx":
        from openpyxl import load_workbook
        workbook = load_workbook(path,read_only=True,data_only=True)
        try:
            ws = workbook.active
            if ws.max_row > 10001 or ws.max_column > 50:
                raise ValueError("XLSX exceeds 10000 rows or 50 columns")
            table=[["" if v is None else str(v) for v in row]
                   for row in ws.iter_rows(values_only=True,max_row=ws.max_row,max_col=ws.max_column)]
        finally:
            workbook.close()
    else:
        raise ValueError("Unsupported dataset type")
    if not table or not table[0] or len(table[0])>50 or len(table)>10001:
        raise ValueError("Dataset must contain <=10000 rows and <=50 columns")
    header=table[0]
    if any(not v.strip() for v in header) or len(set(header))!=len(header):
        raise ValueError("Dataset headers must be nonempty and unique")
    rows=table[1:]
    if any(len(row)!=len(header) for row in rows):
        raise ValueError("Inconsistent data column counts")
    return header, rows


def analyze(header: list[str], rows: list[list[str]]) -> dict:
    if len(rows)>10000: raise ValueError("Too many observations")
    data = {"rows":len(rows),"columns":len(header),"duplicates":len(rows)-len(set(map(tuple,rows))),
            "missing":{h:sum(not str(row[i]).strip() for row in rows) for i,h in enumerate(header)},
            "numeric":{}}
    for idx, h in enumerate(header):
        vals=[]
        for row in rows:
            v=str(row[idx]).strip()
            if not v: continue
            try:
                x=float(v)
            except ValueError:
                vals=[]
                break
            if not math.isfinite(x):
                raise ValueError("Dataset contains non-finite numeric values")
            vals.append(x)
        if vals:
            data["numeric"][h]={
                "count":len(vals),"min":min(vals),"max":max(vals),
                "mean":round(sum(vals)/len(vals),6)}
    return data


def sectioned(text: str) -> list[tuple[str,str]]:
    """Bound model output so all renderers use the same verified text."""
    if not isinstance(text,str) or not 15<=len(text.strip())<=45000:
        raise ValueError("Work content must be substantive and bounded")
    result=[]
    for line in text.splitlines():
        line=line.strip()
        if not line: continue
        if line.startswith(("# ","## ")):
            heading=line.lstrip("# ").strip()
            if not heading or len(heading)>100:
                raise ValueError("Artifact heading missing or exceeds 100 characters")
            result.append((heading,""))
        elif result:
            title,body=result[-1]
            result[-1]=(title,body+"\n"+line)
        else:
            result.append(("Overview",line))
    if len(result) > 24 or any(len(body) > 8000 for _, body in result):
        raise ValueError("Artifact section exceeds bounded size or section count")
    return result or [("Overview",text)]


def csv_escape(value):
    v=str(value)
    return "'"+v if v.lstrip().startswith(("=","+","-","@","\t","\r")) else v


def render_one(kind: str, output: Path, title: str, content: str,
               table: tuple[list[str],list[list[str]]] | None, source_urls: list[str]):
    """Create one real file. Optional rendering dependencies are isolated."""
    output.parent.mkdir(parents=True,exist_ok=True)
    sections=sectioned(content)
    lines=[title,""]+[f"{h}\n{body}\n" for h,body in sections]
    if source_urls: lines+=["Sources"]+source_urls
    prose="\n".join(lines)
    if kind in ("txt","md"):
        output.write_text(prose,encoding="utf-8")
    elif kind=="json":
        output.write_text(json.dumps({"schema_version":1,"title":title,
            "sections":[{"heading":h,"content":b} for h,b in sections],
            "sources":source_urls,"dataset_rows":len(table[1]) if table else None},
            ensure_ascii=False,indent=2),encoding="utf-8")
    elif kind=="html":
        body="".join(f"<section><h2>{html.escape(h)}</h2><p>{html.escape(b).replace(chr(10),'<span class=break></span>')}</p></section>"
                     for h,b in sections)
        if source_urls:
            body += "<section><h2>Sources</h2>" + "".join(
                "<p>" + html.escape(src) + "</p>" for src in source_urls) + "</section>"
        output.write_text("<!doctype html><html lang='en'><head><meta charset='utf-8'>"+
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"+
            "<title>"+html.escape(title)+"</title><style>body{font:17px/1.6 system-ui;"+
            "max-width:850px;padding:2rem;margin:auto;color:#172333}h1,h2{line-height:1.2}"+
            "section{margin:2rem 0}.break{display:block}</style></head><body><h1>"+
            html.escape(title)+"</h1>"+body+"</body></html>",encoding="utf-8")
    elif kind=="csv":
        if not table: raise ValueError("CSV output requires uploaded source dataset")
        with output.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.writer(f)
            w.writerow([csv_escape(x) for x in table[0]])
            w.writerows([[csv_escape(x) for x in row] for row in table[1]])
    elif kind in ("docx","pptx","xlsx","pdf"):
        from .work_design import render_docx, render_pptx, render_xlsx, render_pdf
        {"docx": render_docx, "pptx": render_pptx,
         "xlsx": render_xlsx, "pdf": render_pdf}[kind](
            output, title, sections, table, source_urls)
    elif kind in ("png","svg"):
        if not table: raise ValueError("Charts require real uploaded data")
        metrics=analyze(*table)["numeric"]
        if not metrics: raise ValueError("No valid numeric dataset for chart")
        from matplotlib.figure import Figure
        fig=Figure(figsize=(9,5),layout="constrained")
        ax=fig.subplots()
        labels=list(metrics)[:10];values=[metrics[x]["mean"] for x in labels]
        ax.bar(labels,values);ax.set_ylabel("Column mean");ax.set_title(title[:80]);ax.tick_params(axis="x",labelrotation=35)
        fig.savefig(output,format=kind,dpi=160)
    else: raise ValueError("Unsupported deliverable format")
