"""Reproducible, editable business artifact layouts from the approved narrative.

No model runs in a renderer. Data charts and formulas are source-derived only.
"""
from __future__ import annotations

import html
import math
import re
from pathlib import Path

NAVY = "18273D"
BLUE = "2368AC"
TEAL = "137B79"
PALE = "EFF5FA"
GREY = "506278"


def _dataset_profile(table):
    if not table:
        return None
    from .work_skills import analyze
    return analyze(*table)


def render_docx(path: Path, title: str, sections, table, sources):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(.78)
    section.bottom_margin = Inches(.74)
    section.left_margin = section.right_margin = Inches(.85)
    section.header_distance = section.footer_distance = Inches(.33)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Aptos", Pt(10)
    normal.font.color.rgb = RGBColor.from_string(NAVY)
    normal.paragraph_format.space_after = Pt(7)
    normal.paragraph_format.line_spacing = 1.16
    for name, size in (("Title", 26), ("Heading 1", 15), ("Heading 2", 12)):
        st = doc.styles[name]
        st.font.name, st.font.size = "Aptos Display", Pt(size)
        st.font.color.rgb = RGBColor.from_string(BLUE)
        st.font.bold = True
        st.paragraph_format.space_before = Pt(14)
        st.paragraph_format.space_after = Pt(7)
        st.paragraph_format.keep_with_next = True

    header = section.header.paragraphs[0]
    header.text = "RIZZLER   /   RESEARCH & ANALYSIS"
    header.style = "Caption"
    header.runs[0].font.color.rgb = RGBColor.from_string(TEAL)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.add_run("RIZZLER  •  ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)

    doc.add_heading(title, 0)
    for heading, body in sections:
        doc.add_heading(heading, level=1)
        for line in body.split("\n"):
            if not line.strip():
                continue
            # Preserve prose verbatim; do not convert unverified markdown to facts.
            paragraph = doc.add_paragraph(line.strip())
            paragraph.paragraph_format.widow_control = True

    if table:
        profile = _dataset_profile(table)
        doc.add_heading("Dataset overview", level=1)
        summary = doc.add_table(rows=1, cols=2)
        summary.style = "Light Shading Accent 1"
        summary.alignment = WD_TABLE_ALIGNMENT.CENTER
        summary.rows[0].cells[0].text = "Measure"
        summary.rows[0].cells[1].text = "Verified source value"
        for key, value in (("Observations", profile["rows"]),
                           ("Columns", profile["columns"]),
                           ("Duplicate rows", profile["duplicates"])):
            cells = summary.add_row().cells
            cells[0].text, cells[1].text = key, str(value)
        doc.add_paragraph("Preview of source rows (at most 10; full data is available in the workbook).")
        if len(table[0]) <= 8 and table[1]:
            preview = doc.add_table(rows=1, cols=len(table[0]))
            preview.style = "Light Shading Accent 1"
            for cell, value in zip(preview.rows[0].cells, table[0]):
                cell.text = value
            for record in table[1][:10]:
                for cell, value in zip(preview.add_row().cells, record):
                    cell.text = str(value)[:140]
            for row in preview.rows:
                for cell in row.cells:
                    cell.vertical_alignment = 1
    if sources:
        doc.add_heading("Sources", level=1)
        for source in sources:
            p = doc.add_paragraph(source)
            p.style = "Normal"
            p.paragraph_format.space_after = Pt(5)
    doc.core_properties.title = title
    doc.core_properties.subject = "Source-bound analysis"
    doc.core_properties.author = "Rizzler Work Agent"
    doc.save(path)


def _split_prose(value: str, limit: int = 380) -> list[str]:
    """Do not lose words or split long tokens with untraceable transformations."""
    words = value.split()
    if any(len(w) > limit for w in words):
        raise ValueError("Single unbreakable word exceeds slide capacity")
    chunks, current = [], []
    for word in words:
        if current and len(" ".join(current + [word])) > limit:
            chunks.append(" ".join(current))
            current = []
        current.append(word)
    return chunks + ([" ".join(current)] if current or not chunks else [])


def render_pptx(path: Path, title: str, sections, table, sources):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import MSO_AUTO_SIZE
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE

    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    color = lambda s: RGBColor.from_string(s)
    def set_style(paragraph, size, *, bold=False, foreground=NAVY):
        paragraph.font.name = "Aptos"
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = color(foreground)

    def create(title_text, *, cover=False):
        slide = deck.slides.add_slide(deck.slide_layouts[0 if cover else 5])
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = color(NAVY if cover else "FFFFFF")
        heading = slide.shapes.title
        heading.text = title_text
        heading.left, heading.top = Inches(.72), Inches(.63 if cover else .42)
        heading.width, heading.height = Inches(11.8), Inches(1.3 if cover else 1.0)
        heading.text_frame.word_wrap = True
        heading.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        for p in heading.text_frame.paragraphs:
            set_style(p, 30 if cover else 27, bold=True,
                      foreground="FFFFFF" if cover else NAVY)
        if not cover:
            strip = slide.shapes.add_shape(1, Inches(.72), Inches(1.44),
                                           Inches(1.0), Inches(.05))
            strip.fill.solid()
            strip.fill.fore_color.rgb = color(TEAL)
            strip.line.fill.background()
            foot = slide.shapes.add_textbox(Inches(.72), Inches(7.05),
                                            Inches(11.5), Inches(.26))
            foot.text_frame.paragraphs[0].text = (
                f"RIZZLER   /   SOURCE-BOUND ANALYSIS                                      {len(deck.slides):02d}")
            set_style(foot.text_frame.paragraphs[0], 9, foreground=GREY)
        return slide

    intro = create(title, cover=True)
    if intro.placeholders and len(intro.placeholders) > 1:
        intro.placeholders[1].text = "Research  /  Analysis  /  Deliverables"
        for p in intro.placeholders[1].text_frame.paragraphs:
            set_style(p, 19, foreground="FFFFFF")
    for heading, body in sections:
        for i, chunk in enumerate(_split_prose(body)):
            slide = create(heading if i == 0 else f"{heading} (cont.)")
            box = slide.shapes.add_textbox(Inches(.82), Inches(1.86),
                                            Inches(11.35), Inches(4.55))
            tf = box.text_frame
            tf.clear()
            tf.word_wrap = True
            tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
            tf.margin_top = Inches(.12)
            tf.margin_left = Inches(.10)
            p = tf.paragraphs[0]
            p.text = chunk
            p.space_after = Pt(6)
            set_style(p, 19, foreground=NAVY)

    if table and table[1]:
        metrics = _dataset_profile(table)["numeric"]
        if metrics:
            col = next(iter(metrics))
            idx = table[0].index(col)
            categorical = next((i for i,h in enumerate(table[0])
                                if h not in metrics), None)
            data = []
            for n,row in enumerate(table[1][:8]):
                try:
                    amount = float(row[idx])
                except (ValueError, TypeError):
                    continue
                if not math.isfinite(amount):
                    continue
                label = str(row[categorical])[:18] if categorical is not None else str(n+1)
                data.append((label, amount))
            if data:
                slide = create("Dataset sample — " + col[:65])
                chart_data = CategoryChartData()
                chart_data.categories = [r[0] for r in data]
                chart_data.add_series(col[:70], [r[1] for r in data])
                chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,
                    Inches(1.15), Inches(1.84), Inches(10.65),
                    Inches(4.42), chart_data).chart
                chart.has_legend = False
                chart.has_title = False
                chart.value_axis.has_major_gridlines = True
                chart.category_axis.tick_labels.font.size = Pt(11)

    if sources:
        # Long provider URLs stay intact as actual hyperlink targets and in
        # presenter notes. The visible slide uses bounded, readable labels.
        for start in range(0, len(sources), 5):
            slide = create("Sources" if start == 0 else "Sources (cont.)")
            for i, source in enumerate(sources[start:start+5]):
                pbox = slide.shapes.add_textbox(Inches(1.02), Inches(1.86+i*.75),
                                                Inches(10.85), Inches(.59))
                run = pbox.text_frame.paragraphs[0].add_run()
                run.text = source if len(source) <= 118 else (
                    source[:95] + "… [open complete source]")
                run.hyperlink.address = source
                run.font.name = "Aptos"
                run.font.size = Pt(12)
                run.font.color.rgb = color(BLUE)
                # Notes retain the complete source for auditing, even when
                # the visual label must be shortened for readability.
                notes = slide.notes_slide.notes_text_frame
                notes.text = (notes.text or "") + "\n" + source
    if len(deck.slides) > 100:
        raise ValueError("Presentation exceeds 100 slides; split the assignment")
    deck.core_properties.title = title
    deck.core_properties.author = "Rizzler Work Agent"
    deck.save(path)


def _safe_cell(value: str):
    """Preserve text identifiers and neutralize every spreadsheet formula prefix."""
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value


def _numeric_column(column_name, values):
    if re.search(r"(?:^|[_\s])(id|code|postal|zip|sku|phone|account|reference)(?:$|[_\s])",
                 column_name, flags=re.I):
        return False
    nonblank = [str(x).strip() for x in values if str(x).strip()]
    return bool(nonblank) and all(
        re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", x) and len(x.replace("-","").replace(".",""))<=14
        and math.isfinite(float(x)) for x in nonblank)


def render_xlsx(path: Path, title: str, sections, table, sources):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from openpyxl.chart import BarChart, Reference

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([title])
    ws.append(["Section", "Content"])
    for heading, body in sections:
        ws.append([_safe_cell(heading), _safe_cell(body)])
    ws.freeze_panes = "B3"
    ws.column_dimensions["A"].width = 31
    ws.column_dimensions["B"].width = 88
    ws.row_dimensions[1].height = 32
    ws["A1"].font = Font(name="Aptos Display", size=20, bold=True, color=NAVY)
    for cell in ws[2]:
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(name="Aptos", size=11, bold=True, color="FFFFFF")
    for row in ws.iter_rows(min_row=3, min_col=2, max_col=2):
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
    if table:
        headers, records = table
        data = wb.create_sheet("Data")
        data.append([_safe_cell(h) for h in headers])
        numeric = {i for i,h in enumerate(headers)
                   if _numeric_column(h, [row[i] for row in records])}
        for row in records:
            data.append([
                (float(value) if str(value).strip() and i in numeric
                 else (_safe_cell(value) if str(value).strip() else None))
                for i,value in enumerate(row)])
        data.freeze_panes = "A2"
        data.auto_filter.ref = data.dimensions
        for i, name in enumerate(headers, 1):
            data.column_dimensions[get_column_letter(i)].width = min(28, max(13,len(name)+2))
            cell = data.cell(1,i)
            cell.fill = PatternFill("solid", fgColor=NAVY)
            cell.font = Font(color="FFFFFF", bold=True)
        checks = wb.create_sheet("Checks")
        checks.append(["Metric", "Workbook formula", "Independent expected", "Verification"])
        n = len(records)
        checks.append(["Source rows",
                       f"=ROWS(Data!A2:A{n+1})" if n else "=COUNTA(Data!A2:A2)",
                       n, "Pending spreadsheet recalculation"])
        profile = _dataset_profile(table)
        for i in sorted(numeric):
            stats = profile["numeric"].get(headers[i])
            if not stats:
                continue
            col = get_column_letter(i+1)
            rng = f"Data!{col}2:{col}{max(2,n+1)}"
            for name, fun, expected in (
                ("Count", "COUNT", stats["count"]),
                ("Mean", "AVERAGE", stats["mean"]),
                ("Minimum", "MIN", stats["min"]),
                ("Maximum", "MAX", stats["max"]),
            ):
                checks.append([f"{headers[i]} — {name}", f"={fun}({rng})",
                               expected, "Pending spreadsheet recalculation"])
        checks.freeze_panes = "A2"
        checks.column_dimensions["A"].width = 36
        checks.column_dimensions["B"].width = 37
        checks.column_dimensions["C"].width = 24
        checks.column_dimensions["D"].width = 38
        for cell in checks[1]:
            cell.fill = PatternFill("solid", fgColor=NAVY)
            cell.font = Font(color="FFFFFF", bold=True)
        for row in checks.iter_rows(min_row=2):
            row[2].number_format = "0.######"

        if numeric and records:
            dashboard = wb.create_sheet("Dashboard", 1)
            dashboard["A1"] = "Source-derived numeric overview"
            dashboard["A1"].font = Font(size=16, color=NAVY, bold=True)
            dashboard.append(["Column","Mean"])
            for h in [headers[i] for i in sorted(numeric)][:10]:
                dashboard.append([h, profile["numeric"][h]["mean"]])
            for cell in dashboard[2]:
                cell.fill = PatternFill("solid", fgColor=NAVY)
                cell.font = Font(color="FFFFFF", bold=True)
            dashboard.column_dimensions["A"].width = 28
            dashboard.column_dimensions["B"].width = 22
            if dashboard.max_row >= 3:
                chart = BarChart()
                chart.type = "col"
                chart.title = "Field means (different units may not be comparable)"
                chart.y_axis.title = "Source-derived mean"
                chart.add_data(Reference(dashboard,min_col=2,min_row=2,max_row=dashboard.max_row),
                               titles_from_data=True)
                chart.set_categories(Reference(dashboard,min_col=1,min_row=3,max_row=dashboard.max_row))
                chart.width, chart.height = 18, 9
                dashboard.add_chart(chart, "D3")
    if sources:
        sheet = wb.create_sheet("Sources")
        sheet.column_dimensions["A"].width = 100
        for source in sources:
            sheet.append([source])
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.save(path)


def render_pdf(path: Path, title: str, sections, table, sources):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font = "Helvetica"
    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if font_path.is_file():
        if "RizzlerDejaVu" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("RizzlerDejaVu", str(font_path)))
        font = "RizzlerDejaVu"
    base = getSampleStyleSheet()
    para = ParagraphStyle("RizzlerBody", parent=base["BodyText"], fontName=font,
                          fontSize=9.5, leading=15, textColor=colors.HexColor("#"+NAVY),
                          spaceAfter=7, splitLongWords=True)
    heading = ParagraphStyle("RizzlerHeading", parent=para, fontSize=14, leading=19,
                             textColor=colors.HexColor("#"+BLUE),
                             spaceBefore=13, spaceAfter=8, keepWithNext=True)
    cover = ParagraphStyle("RizzlerTitle", parent=para, fontSize=22, leading=29,
                           textColor=colors.HexColor("#"+NAVY), spaceAfter=20)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=48, rightMargin=48,
                            topMargin=58, bottomMargin=56, title=title,
                            author="Rizzler Work Agent")
    blocks = [Paragraph(html.escape(title), cover), Spacer(1, 7)]
    for h, body in sections:
        blocks.append(Paragraph(html.escape(h), heading))
        for line in body.split("\n"):
            if line.strip():
                blocks.append(Paragraph(html.escape(line), para))
    if table:
        profile = _dataset_profile(table)
        blocks.append(Paragraph("Dataset overview", heading))
        rows = [["Measure", "Independently computed value"],
                ["Observations", str(profile["rows"])],
                ["Columns", str(profile["columns"])],
                ["Duplicate rows", str(profile["duplicates"])]]
        metric_table = Table(rows, colWidths=[175, 235], hAlign="LEFT")
        metric_table.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(-1,0),colors.HexColor("#"+NAVY)),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("TEXTCOLOR",(0,1),(-1,-1),colors.HexColor("#"+NAVY)),
            ("BOTTOMPADDING",(0,0),(-1,-1),7),
            ("TOPPADDING",(0,0),(-1,-1),7),
            ("LINEBELOW",(0,1),(-1,-1),.3,colors.HexColor("#D8E3EA")),
        ]))
        blocks.append(metric_table)
    if sources:
        blocks.append(Paragraph("Sources", heading))
        for source in sources:
            blocks.append(Paragraph(html.escape(source), para))
    def footer(canvas, current):
        canvas.saveState()
        width, _ = A4
        canvas.setStrokeColor(colors.HexColor("#D8E3EA"))
        canvas.line(48, 42, width-48, 42)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#"+GREY))
        canvas.drawString(48, 29, "RIZZLER  /  SOURCE-BOUND ANALYSIS")
        canvas.drawRightString(width-48, 29, str(current.page))
        canvas.restoreState()
    doc.build(blocks, onFirstPage=footer, onLaterPages=footer)
