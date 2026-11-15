"""Actual page-render QA. Required mode refuses publication without the renderer.

This detects blank pages, page bounds and conversion failures; it is not an
AI aesthetic judge, source fact-checker or calibrated accessibility audit.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def quality_mode() -> str:
    mode = os.environ.get("RIZZLER_ARTIFACT_QA", "structural").strip().lower()
    if mode not in ("strict", "structural", "agentic"):
        raise ValueError("RIZZLER_ARTIFACT_QA must be agentic, strict or structural")
    return mode


def inspect_visual(path: Path, kind: str, *, required: bool = False) -> dict:
    if kind not in ("pdf", "docx", "pptx"):
        return {"status": "not_applicable"}
    if not required:
        return {"status": "not_executed", "reason": "strict_render_qa_disabled"}
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("Strict artifact QA requires PyMuPDF") from exc

    with tempfile.TemporaryDirectory(prefix="rizzler-visual-") as temp:
        root = Path(temp)
        pdf = path
        if kind != "pdf":
            binary = shutil.which("libreoffice") or shutil.which("soffice")
            if not binary:
                raise RuntimeError("Strict artifact QA requires LibreOffice Writer/Impress")
            # Per-invocation profile avoids global LibreOffice lock contention
            # between concurrently scheduled document specialists.
            output_dir = root/"pages"
            output_dir.mkdir()
            profile = (root/"profile").as_uri()
            try:
                result = subprocess.run(
                    [binary,"--headless","--nologo","--nodefault","--nofirststartwizard",
                     "-env:UserInstallation="+profile,
                     "--convert-to","pdf","--outdir",str(output_dir),str(path)],
                    capture_output=True, timeout=65, check=False)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Office page rendering exceeded time budget") from exc
            pdf = output_dir/(path.stem+".pdf")
            if result.returncode or not pdf.is_file() or pdf.stat().st_size > 50_000_000:
                raise RuntimeError("Office page rendering failed")
        pages = []
        with fitz.open(pdf) as doc:
            if doc.page_count < 1 or doc.page_count > 120:
                raise ValueError("Visual QA found invalid page count")
            if kind == "pptx":
                from pptx import Presentation
                if doc.page_count != len(Presentation(path).slides):
                    raise ValueError("Rendered slide count differs from source deck")
            for index, page in enumerate(doc):
                if page.rect.width < 100 or page.rect.height < 100:
                    raise ValueError("Rendered page dimensions are unusable")
                words = page.get_text("words")
                if len(words) < 2:
                    raise ValueError("Rendered page is blank or not text-readable")
                if any(w[0] < -1 or w[1] < -1 or
                       w[2] > page.rect.width+1 or w[3] > page.rect.height+1
                       for w in words):
                    raise ValueError("Rendered page contains clipped/out-of-bounds words")
                # Rasterize *every page*, rather than validating just the PDF
                # header or shape definitions. Hashes provide inspectable
                # evidence without persisting the customer's page pixels.
                pix = page.get_pixmap(matrix=fitz.Matrix(.9,.9),
                                      colorspace=fitz.csRGB, alpha=False)
                if pix.width < 100 or pix.height < 100:
                    raise ValueError("Rendered page is below inspection resolution")
                pages.append({"page":index+1, "words":len(words),
                              "pixel_sha256":hashlib.sha256(pix.samples).hexdigest()})
        return {"status":"rendered_pages_verified", "pages":len(pages),
                "per_page":pages,
                "limitations":"Raster and page bounds QA; human design and a11y review still required"}
