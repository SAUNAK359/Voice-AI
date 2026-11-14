"""Page-faithful preview rendering through an isolated Office-to-PDF conversion.

The preview uses actual page pixels, not reconstructed slide or paragraph text.
LibreOffice and Microsoft Office may paginate differently; no false claim of
pixel-identical fidelity to all Office versions or installed fonts is made.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

MAX_RENDER_BYTES=50_000_000
MAX_PAGES=400

def _cache_root(root,owner,sha):
    safe=hashlib.sha256((owner+":"+sha).encode()).hexdigest()
    directory=Path(root).resolve()/"render_cache"/safe
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    return directory

def source_pdf(root,owner,path,sha,kind):
    path=Path(path).resolve()
    if not path.is_file() or path.is_symlink() or path.stat().st_size>MAX_RENDER_BYTES:
        raise ValueError("Artifact cannot be rendered safely")
    if kind=="pdf":return path
    if kind not in ("pptx","docx","xlsx"):
        raise ValueError("No page renderer for this format")
    binary=shutil.which("libreoffice") or shutil.which("soffice")
    if not binary:raise RuntimeError("Office renderer is not installed")
    cache=_cache_root(root,owner,sha)
    output=cache/"converted.pdf"
    if output.exists() and 0<output.stat().st_size<=100_000_000:return output
    with tempfile.TemporaryDirectory(prefix="rizzler-pages-",dir=cache) as directory:
        staging=Path(directory)
        # Predictable basename prevents a user-controlled filename from
        # affecting output lookup, options or conversion profile.
        original=staging/("source."+kind)
        shutil.copyfile(path,original)
        dest=staging/"out";dest.mkdir()
        profile=(staging/"profile").as_uri()
        try:
            completed=subprocess.run([
                binary,"--headless","--nologo","--nodefault","--nofirststartwizard",
                "-env:UserInstallation="+profile,
                "--convert-to","pdf","--outdir",str(dest),str(original)],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                check=False,timeout=100)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Office conversion timeout") from exc
        rendered=dest/"source.pdf"
        if completed.returncode or not rendered.is_file() or not 0<rendered.stat().st_size<=100_000_000:
            raise RuntimeError("Office conversion failed")
        try:
            import fitz
            with fitz.open(rendered) as pdf:
                if not 1<=pdf.page_count<=MAX_PAGES:raise ValueError("Invalid rendered page count")
        except ImportError as exc:raise RuntimeError("PyMuPDF required") from exc
        os.replace(rendered,output)
    return output

def page_info(root,owner,path,sha,kind):
    import fitz
    pdf=source_pdf(root,owner,path,sha,kind)
    with fitz.open(pdf) as doc:
        if not 1<=doc.page_count<=MAX_PAGES:raise ValueError("Page count exceeds viewer limit")
        return {"pages":doc.page_count,"format":kind,"renderer":"libreoffice_pdf" if kind!="pdf" else "native_pdf",
                "fidelity":"rendered_pages","limitations":"Office layout depends on installed fonts and LibreOffice"}
def render_page(root,owner,path,sha,kind,page):
    if type(page) is not int or not 1<=page<=MAX_PAGES:
        raise ValueError("Invalid page")
    import fitz
    pdf=source_pdf(root,owner,path,sha,kind)
    with fitz.open(pdf) as doc:
        if not 1<=page<=doc.page_count:raise ValueError("Page outside document")
        p=doc.load_page(page-1)
        scale=min(2.5,max(1.0,1800/max(p.rect.width,p.rect.height)))
        pix=p.get_pixmap(matrix=fitz.Matrix(scale,scale),
                         colorspace=fitz.csRGB,alpha=False)
        if pix.width*pix.height>8_000_000:raise ValueError("Rendered page too large")
        return pix.tobytes("png")
