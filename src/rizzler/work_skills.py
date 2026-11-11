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
            result.append((line.lstrip("# ").strip()[:100],""))
        elif result:
            title,body=result[-1]
            result[-1]=(title,(body+"\n"+line)[:8000])
        else:
            result.append(("Overview",line))
    return result[:24] or [("Overview",text[:8000])]


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
    elif kind=="docx":
        from docx import Document
        from docx.shared import Pt, Inches
        d=Document(); d.add_heading(title,0)
        for h,b in sections:
            d.add_heading(h,level=1)
            d.add_paragraph(b)
        if source_urls:
            d.add_heading("Sources",level=1)
            for src in source_urls:d.add_paragraph(src)
        d.styles["Normal"].font.size=Pt(10.5)
        d.save(output)
    elif kind=="pdf":
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        style=getSampleStyleSheet()
        story=[Paragraph(html.escape(title),style["Title"]),Spacer(1,15)]
        for h,b in sections:
            story += [Paragraph(html.escape(h),style["Heading2"])]
            for paragraph in b.split("\n"):
                if paragraph.strip():story += [Paragraph(html.escape(paragraph),style["BodyText"]),Spacer(1,6)]
        if source_urls:
            story.append(Paragraph("Sources",style["Heading2"]))
            for url in source_urls:story.append(Paragraph(html.escape(url),style["BodyText"]))
        SimpleDocTemplate(str(output),pagesize=A4,rightMargin=45,leftMargin=45,
                          topMargin=50,bottomMargin=50).build(story)
    elif kind=="pptx":
        from pptx import Presentation
        from pptx.util import Inches,Pt
        from pptx.dml.color import RGBColor
        p=Presentation();p.slide_width=Inches(13.333);p.slide_height=Inches(7.5)
        cover=p.slides.add_slide(p.slide_layouts[0])
        cover.shapes.title.text=title
        cover.placeholders[1].text="Rizzler Work Agent • Verified report content"
        if len(sections)>24:
            raise ValueError("Too many presentation sections")
        for h,b in sections:
            slide=p.slides.add_slide(p.slide_layouts[1])
            slide.shapes.title.text=h
            body=slide.placeholders[1]
            # A slide cannot silently discard source content.
            if len(b)>850:
                raise ValueError("Slide section exceeds 850 characters; revise source")
            body.text=b
            for para in body.text_frame.paragraphs:para.font.size=Pt(18)
        if source_urls:
            s=p.slides.add_slide(p.slide_layouts[1]);s.shapes.title.text="Sources"
            s.placeholders[1].text="\n".join(source_urls[:12])
        p.save(output)
    elif kind=="xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill,Alignment
        from openpyxl.utils import get_column_letter
        wb=Workbook();summary=wb.active;summary.title="Summary"
        summary.append([title]);summary.append(["Section","Content"])
        for h,b in sections:summary.append([h,b])
        summary.column_dimensions["A"].width=28;summary.column_dimensions["B"].width=85
        for cell in summary[2]:cell.font=Font(bold=True,color="FFFFFF");cell.fill=PatternFill("solid",fgColor="243B53")
        for row in summary.iter_rows(min_row=3,min_col=2,max_col=2):
            row[0].alignment=Alignment(wrap_text=True,vertical="top")
        if table:
            ws=wb.create_sheet("Data");ws.append(table[0])
            for row in table[1]:ws.append([csv_escape(v) for v in row])
            ws.freeze_panes="A2";ws.auto_filter.ref=ws.dimensions
            for i,_ in enumerate(table[0],1):ws.column_dimensions[get_column_letter(i)].width=18
        if source_urls:
            ws=wb.create_sheet("Sources")
            for u in source_urls:ws.append([u])
        wb.save(output)
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
