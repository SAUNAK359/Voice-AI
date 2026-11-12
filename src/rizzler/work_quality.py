"""Independent, deterministic post-render quality gates.

This augments (not replaces) byte-level structural verification. It cannot
certify aesthetic superiority or factual truth without external ground truth.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import zipfile

from .artifacts import verify_artifact
from .work_ir import ArtifactIR
import html as html_lib


def inspect_artifact(path: Path, kind: str, *,
                     dataset_rows: int | None = None,
                     bundle_receipts: dict | None = None,
                     artifact_ir: ArtifactIR | None = None,
                     dataset_summary: dict | None = None,
                     visual_required: bool = False) -> dict:
    receipt = verify_artifact(path, kind)
    checks = ["sha256_receipt_valid", "format_structure_valid"]
    details: dict = {}
    if kind == "docx":
        from docx import Document
        doc = Document(path)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        if not paragraphs or len("".join(paragraphs)) < 40:
            raise ValueError("Word document lacks substantive text")
        details["paragraphs"] = len(paragraphs)
        checks.append("readable_docx_paragraphs")
    elif kind == "pptx":
        from pptx import Presentation
        presentation = Presentation(path)
        if len(presentation.slides) < 2:
            raise ValueError("PowerPoint lacks substantive slides")
        for slide in presentation.slides:
            if not any(shape.has_text_frame and shape.text.strip() for shape in slide.shapes):
                raise ValueError("PowerPoint contains an empty slide")
            for shape in slide.shapes:
                if (shape.left < -1000 or shape.top < -1000 or
                    shape.left + shape.width > presentation.slide_width + 1000 or
                    shape.top + shape.height > presentation.slide_height + 1000):
                    raise ValueError("PowerPoint shape extends beyond slide canvas")
        details["slides"] = len(presentation.slides)
        checks.append("nonempty_editable_slides_within_canvas")
    elif kind == "xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=False)
        try:
            if "Summary" not in wb.sheetnames:
                raise ValueError("XLSX summary worksheet missing")
            if dataset_rows is not None:
                if "Data" not in wb.sheetnames:
                    raise ValueError("XLSX source data worksheet missing")
                observed = wb["Data"].max_row - 1
                if observed != dataset_rows:
                    raise ValueError("XLSX source row count differs from computed dataset")
                details["dataset_rows"] = observed
                if "Checks" not in wb.sheetnames:
                    raise ValueError("Dataset formula-check worksheet missing")
                formula = (f"=ROWS(Data!A2:A{dataset_rows+1})" if dataset_rows else "=COUNTA(Data!A2:A2)")
                if wb["Checks"]["B2"].value != formula or wb["Checks"]["C2"].value != dataset_rows:
                    raise ValueError("Workbook source-row formula or expected value mismatch")
                checks.append("formula_contract_matches_independent_row_count")
            details["sheets"] = wb.sheetnames
            checks.append("required_worksheets_present")
        finally:
            wb.close()
        from .work_formula import verify_workbook
        details["formula_validation"] = verify_workbook(
            path, dataset_summary=dataset_summary,
            require_recalculation=visual_required and dataset_rows is not None)
        checks.append("independently_evaluated_formula_contract")
        if visual_required and dataset_rows is not None:
            checks.append("spreadsheet_recalculated_by_independent_engine")
    elif kind == "csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        if dataset_rows is None or len(rows) - 1 != dataset_rows:
            raise ValueError("CSV does not reconcile with source row count")
        details["dataset_rows"] = len(rows) - 1
        checks.append("source_row_count_reconciled")
    elif kind == "json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("sections"):
            raise ValueError("Generated JSON lacks structured sections")
        checks.append("nonempty_structured_sections")
    elif kind in ("md", "txt"):
        if len(path.read_text(encoding="utf-8").strip()) < 40:
            raise ValueError("Text report lacks substantive content")
        checks.append("substantive_report_text")
    elif kind == "html":
        if "<section>" not in path.read_text(encoding="utf-8"):
            raise ValueError("HTML report missing sections")
        checks.append("nonempty_html_sections")
    elif kind == "png":
        from PIL import Image
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height = img.size
        if width < 256 or height < 256:
            raise ValueError("PNG output is too small for review")
        details["dimensions"] = [width, height]
        checks.append("decodable_nontrivial_image")
    elif kind == "zip":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "MANIFEST.json" not in names or len(names) != len(set(names)):
                raise ValueError("ZIP artifact manifest missing or duplicate members")
            manifest = json.loads(archive.read("MANIFEST.json"))
            entries = manifest.get("files", [])
            if not isinstance(entries, list):
                raise ValueError("ZIP manifest malformed")
            expected = bundle_receipts or {}
            if len(entries) != len(expected):
                raise ValueError("ZIP manifest does not cover all artifacts")
            for entry in entries:
                name = entry["name"]
                if name not in expected or name not in names or "/" in name or "\\" in name:
                    raise ValueError("Unsafe or unexpected ZIP member")
                payload = archive.read(name)
                if (hashlib.sha256(payload).hexdigest() != expected[name].sha256 or
                    len(payload) != expected[name].byte_size or
                    entry["sha256"] != expected[name].sha256):
                    raise ValueError("ZIP artifact checksum or size mismatch")
            checks.append("manifest_member_hashes_reconciled")
            details["bundled"] = len(entries)
    # Check information coverage; this does not verify the truth of the claims.
    if artifact_ir is not None and kind in ("docx","pptx","xlsx","json","md","txt","html"):
        headings = [h for h, _ in artifact_ir.sections]
        sources = list(artifact_ir.sources)
        if kind == "docx":
            doc = __import__("docx").Document(path)
            present = [p.text for p in doc.paragraphs]
            actual_sources = [p.text for p in doc.paragraphs if p.text in sources]
            valid = all(h in present for h in headings) and actual_sources == sources
            valid = valid and all(
                " ".join(body.split()) in " ".join(" ".join(present).split())
                for _,body in artifact_ir.sections if body.strip())
        elif kind == "pptx":
            from pptx import Presentation
            deck = Presentation(path)
            slide_titles = [s.shapes.title.text for s in deck.slides if s.shapes.title]
            all_text = "\n".join(shape.text for slide in deck.slides
                                 for shape in slide.shapes if shape.has_text_frame)
            notes = "\n".join(
                s.notes_slide.notes_text_frame.text
                for s in deck.slides if s.has_notes_slide
            )
            urls = [shape.click_action.hyperlink.address
                    for slide in deck.slides for shape in slide.shapes
                    if shape.has_text_frame and shape.click_action.hyperlink.address]
            urls += [run.hyperlink.address
                     for slide in deck.slides for shape in slide.shapes
                     if shape.has_text_frame
                     for paragraph in shape.text_frame.paragraphs
                     for run in paragraph.runs if run.hyperlink.address]
            valid = all(h in slide_titles for h in headings) and all(
                src in all_text or src in notes or src in urls for src in sources)
            from .work_design import _split_prose
            valid = valid and all(
                part in " ".join(all_text.split())
                for _,body in artifact_ir.sections for part in _split_prose(body)
                if part.strip())
        elif kind == "xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True)
            try:
                present = [r[0] for r in wb["Summary"].iter_rows(
                           min_row=3, min_col=1, max_col=1, values_only=True)]
                actual_sources = ([r[0] for r in wb["Sources"].iter_rows(values_only=True)]
                                  if "Sources" in wb else [])
                cells = list(wb["Summary"].iter_rows(min_row=3,min_col=2,max_col=2,values_only=True))
                valid = (present == headings and actual_sources == sources
                         and all((cell[0] == body or cell[0] == "'"+body)
                                 for cell,(_,body) in zip(cells,artifact_ir.sections)))
            finally:
                wb.close()
        elif kind == "json":
            data = json.loads(path.read_text(encoding="utf-8"))
            valid = ([s.get("heading") for s in data.get("sections",[])] == headings
                     and [s.get("content") for s in data.get("sections",[])] ==
                           [body for _,body in artifact_ir.sections]
                     and data.get("sources") == sources)
        else:
            rendered = path.read_text(encoding="utf-8")
            expected = [html_lib.escape(h) if kind=="html" else h for h in headings]
            expected_sources = ([html_lib.escape(src) for src in sources]
                                if kind=="html" else sources)
            valid = all(h in rendered for h in expected) and all(
                src in rendered for src in expected_sources)
        if not valid:
            raise ValueError("Artifact IR sections or source provenance missing")
        details["ir_sha256"] = artifact_ir.sha256
        checks.append("artifact_ir_headings_and_sources_reconciled")
    if kind in ("pdf","docx","pptx"):
        from .work_visual import inspect_visual
        details["visual_validation"] = inspect_visual(path,kind,required=visual_required)
        if visual_required:
            checks.append("every_rendered_page_has_visible_in_bounds_text")
    return {"kind":kind,"passed":True,"checks":checks,"metrics":details,
            "limitations":"No claim of independent factual or pixel-level visual perfection"}
