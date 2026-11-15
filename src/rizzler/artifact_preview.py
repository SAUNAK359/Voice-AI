"""Data-only, owner-authenticated artifact preview representation.

Office previews describe actual document contents, not simulated visual fidelity.
All text is rendered with textContent on the client; document macros never run.
"""
from __future__ import annotations
import io, re, zipfile
from xml.etree import ElementTree as ET
from pathlib import Path

MAX_BYTES=35_000_000
MAX_ZIP_MEMBERS=1800
MAX_INFLATED=100_000_000

def _parts(path):
    if path.stat().st_size>MAX_BYTES:raise ValueError("Preview exceeds supported size")
    z=zipfile.ZipFile(path)
    members=z.infolist()
    if len(members)>MAX_ZIP_MEMBERS or sum(e.file_size for e in members)>MAX_INFLATED or z.testzip() is not None:
        z.close();raise ValueError("Invalid Office archive")
    for item in members:
        p=item.filename.replace("\\","/")
        if p.startswith("/") or ".." in p.split("/") or (item.external_attr>>16)&0o170000==0o120000:
            z.close();raise ValueError("Unsafe Office archive")
    return z

def _tokens(z,filename):
    root=ET.fromstring(z.read(filename))
    out=[]
    for p in root.iter():
        if p.tag.rsplit("}",1)[-1] in ("p","tr"):
            parts=[t.text.strip() for t in p.iter() if t.tag.rsplit("}",1)[-1] in ("t","v") and t.text and t.text.strip()]
            if parts:out.append(" ".join(parts)[:2500])
    return out

def render(path:Path,kind:str):
    if kind not in ("pptx","docx","xlsx"):
        raise ValueError("No structured preview available")
    path=Path(path)
    if not path.is_file() or path.is_symlink():raise ValueError("Artifact unavailable")
    if kind=="pptx":
        with _parts(path) as z:
            entries=sorted((s for s in z.namelist() if re.fullmatch(r"ppt/slides/slide[0-9]+\.xml",s)),
                           key=lambda n:int(re.search(r"slide(\d+)",n).group(1)))
            if not entries:raise ValueError("Presentation has no slides")
            slides=[]
            for i,name in enumerate(entries[:100]):
                text=_tokens(z,name)[:150]
                slides.append({"index":i+1,"title":text[0][:200] if text else f"Slide {i+1}","lines":text})
            return {"kind":"pptx","slides":slides,"total":len(entries),"mode":"structured_text_preview","fidelity":"text_only"}
    if kind=="docx":
        with _parts(path) as z:
            if "word/document.xml" not in z.namelist():raise ValueError("Document body missing")
            blocks=_tokens(z,"word/document.xml")[:1000]
            return {"kind":"docx","blocks":blocks,"mode":"structured_text_preview","fidelity":"text_only"}
    try:import openpyxl
    except ImportError:raise ValueError("Workbook preview requires openpyxl") from None
    if path.stat().st_size>MAX_BYTES:raise ValueError("Preview too large")
    wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
    try:
        sheets=[]
        for sh in wb.worksheets[:20]:
            rows=[]
            for i,row in enumerate(sh.iter_rows(values_only=True)):
                if i>=160:break
                rows.append([str(v)[:250] if v is not None else "" for v in row[:60]])
            sheets.append({"name":sh.title[:80],"rows":rows,"truncated":sh.max_row is None or sh.max_row>160})
        return {"kind":"xlsx","sheets":sheets,"mode":"tabular_preview","fidelity":"values_only"}
    finally:wb.close()
