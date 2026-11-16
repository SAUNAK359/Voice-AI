"""Native editable Word and properly typeset PDF from a restricted Markdown AST.

All decisions about content originate in the model; this module only turns
validated prose, heading, list, and table syntax into document objects.
"""
from __future__ import annotations
import html
import re
from pathlib import Path
from urllib.parse import urlsplit

HEADING = re.compile(r"^\s*(#{1,5})\s+(.+)")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)")
DELIM = re.compile(r"^\s*\|?\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+\s*\|?\s*$")
EM = re.compile(r"(\*\*[^*\n]+\*\*|\*[^*\n]+\*|\x60[^\x60]+\x60)")
LINK = re.compile(r"\[([^\]]+)\]\((https://[^\s)]+)\)")


def clean(value: str) -> str:
    # Preserve whitespace around formatting spans; stripping each run glued
    # words together and made the rendered document disagree with its source IR.
    return EM.sub(lambda m:m.group(0).strip("*"+chr(96)), LINK.sub(r"\1",value))


def blocks(sections):
    """Parse limited, data-only Markdown; no embedded HTML execution."""
    result=[]
    for heading,body in sections:
        result.append(("heading",(1,clean(heading).strip())))
        lines=body.splitlines()
        i=0
        while i<len(lines):
            line=lines[i].strip()
            i+=1
            if not line:continue
            match=HEADING.match(line)
            if match:
                result.append(("heading",(min(4,len(match.group(1))+1),clean(match.group(2)).strip())))
                continue
            if re.fullmatch(r"[-*_]{3,}",line):
                result.append(("rule",None))
                continue
            if "|" in line and i<len(lines) and DELIM.match(lines[i]):
                heads=[clean(s).strip() for s in line.strip("|").split("|")]
                i+=1
                rows=[]
                while i<len(lines) and "|" in lines[i]:
                    cells=[clean(s).strip() for s in lines[i].strip().strip("|").split("|")]
                    if len(cells)!=len(heads):break
                    rows.append(cells);i+=1
                if rows and 2<=len(heads)<=10:
                    result.append(("table",[heads]+rows[:60]))
                else:
                    result.append(("paragraph",clean(line)))
                continue
            bullet=BULLET.match(line)
            result.append(("bullet",clean(bullet.group(1))) if bullet
                          else ("paragraph",line))
    return result


def source_label(url: str, number: int):
    host=urlsplit(url).hostname or "unknown source"
    if "grounding-api-redirect" in url:
        return f"[{number}] Provider-grounded reference (publisher URL unverified)"
    return f"[{number}] {host}"


def render_docx(path: Path, title, sections, table, sources):
    from docx import Document
    from docx.shared import Inches,Pt
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc=Document()
    section=doc.sections[0]
    section.top_margin=section.bottom_margin=Inches(.76)
    section.left_margin=section.right_margin=Inches(.85)
    doc.styles["Normal"].font.name="Aptos"
    doc.styles["Normal"].font.size=Pt(10)
    doc.add_heading(clean(title),0)
    for kind,item in blocks(sections):
        if kind=="heading":
            level,text=item
            doc.add_heading(text,level=level)
        elif kind=="table":
            native=doc.add_table(rows=0,cols=len(item[0]))
            native.style="Light Shading Accent 1"
            for rownum,values in enumerate(item):
                cells=native.add_row().cells
                for cell,value in zip(cells,values):
                    cell.text=value
                    if rownum==0:
                        for run in cell.paragraphs[0].runs:run.bold=True
        elif kind=="bullet":
            doc.add_paragraph(item,style="List Bullet")
        elif kind=="rule":
            doc.add_paragraph("—")
        else:
            p=doc.add_paragraph()
            for span in EM.split(item):
                if not span:continue
                run=p.add_run(clean(span))
                run.bold=span.startswith("**") and span.endswith("**")
                run.italic=span.startswith("*") and span.endswith("*") and not run.bold
    if table:
        from .work_skills import analyze
        summary=analyze(*table)
        doc.add_heading("Verified dataset overview",1)
        native=doc.add_table(rows=0,cols=2);native.style="Light Shading Accent 1"
        for a,b in (("Metric","Value"),("Rows",str(summary["rows"])),
                    ("Columns",str(summary["columns"])),
                    ("Duplicates",str(summary["duplicates"]))):
            cells=native.add_row().cells;cells[0].text=a;cells[1].text=b
    if sources:
        doc.add_heading("Source references",1)
        for idx,url in enumerate(sources,1):
            p=doc.add_paragraph()
            p.add_run(source_label(url,idx)+"  ")
            rid=p.part.relate_to(url,RELATIONSHIP_TYPE.HYPERLINK,is_external=True)
            hyperlink=OxmlElement("w:hyperlink")
            hyperlink.set(qn("r:id"),rid)
            run=OxmlElement("w:r");t=OxmlElement("w:t")
            t.text="Open source";run.append(t);hyperlink.append(run);p._p.append(hyperlink)
    doc.core_properties.title=title
    doc.core_properties.subject="Rizzler V15 native structured document"
    doc.core_properties.author="Rizzler Work Intelligence"
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    doc.save(path)


def render_pdf(path: Path,title,sections,table,sources):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,HRFlowable
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font="Helvetica"
    fontpath=Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if fontpath.is_file():
        if "RizzlerDejaVu" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("RizzlerDejaVu",str(fontpath)))
        font="RizzlerDejaVu"
    base=getSampleStyleSheet()
    normal=ParagraphStyle("RizzlerRichBody",parent=base["BodyText"],fontName=font,
          fontSize=9.5,leading=15,spaceAfter=7,splitLongWords=True)
    heading={level:ParagraphStyle("RizzlerRichH"+str(level),parent=normal,
          fontSize=max(11,18-level*2),leading=max(15,22-level*2),
          spaceBefore=12,spaceAfter=7,keepWithNext=True,
          textColor=colors.HexColor("#2368AC")) for level in range(1,5)}
    cover=ParagraphStyle("RizzlerRichTitle",parent=normal,fontSize=22,leading=28,spaceAfter=20)
    def p(value,style=normal):
        escaped=html.escape(value)
        escaped=re.sub(r"\*\*([^*]+)\*\*",r"<b>\1</b>",escaped)
        escaped=re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)",r"<i>\1</i>",escaped)
        return Paragraph(escaped,style)
    def tab(rows):
        cols=len(rows[0]);width=(A4[0]-92)/cols
        t=Table([[p(cell) for cell in row] for row in rows],
                colWidths=[width]*cols,repeatRows=1,hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#E8F4F2")),
            ("GRID",(0,0),(-1,-1),.3,colors.HexColor("#D8E3EA")),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("LEFTPADDING",(0,0),(-1,-1),5),
            ("RIGHTPADDING",(0,0),(-1,-1),5),
            ("TOPPADDING",(0,0),(-1,-1),5),
            ("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        return t
    story=[p(title,cover)]
    for kind,item in blocks(sections):
        if kind=="heading":
            level,words=item;story.append(p(words,heading[level]))
        elif kind=="table":story.append(tab(item))
        elif kind=="bullet":story.append(p("• "+item))
        elif kind=="rule":story.append(HRFlowable(width="100%",thickness=.5))
        else:story.append(p(item))
    if table:
        from .work_skills import analyze
        stats=analyze(*table)
        story.append(p("Verified dataset overview",heading[1]))
        story.append(tab([["Metric","Value"],["Rows",str(stats["rows"])],
                 ["Columns",str(stats["columns"])],
                 ["Duplicates",str(stats["duplicates"])]]))
    if sources:
        story.append(p("Source references",heading[1]))
        for i,url in enumerate(sources,1):
            label=html.escape(source_label(url,i))
            escaped=html.escape(url,quote=True)
            story.append(Paragraph(label+" — <link href=\""+escaped+
                                   "\"><u>Open source</u></link>",normal))
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont("Helvetica",8)
        canvas.drawString(46,28,"RIZZLER / WORK INTELLIGENCE")
        canvas.drawRightString(A4[0]-46,28,str(doc.page))
        canvas.restoreState()
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    SimpleDocTemplate(str(path),pagesize=A4,leftMargin=46,rightMargin=46,
       topMargin=56,bottomMargin=55,title=title).build(story,
       onFirstPage=footer,onLaterPages=footer)
