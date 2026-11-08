"""Deterministic structural inspection for common generated artifact types.

These checks establish file integrity, NOT factual correctness or visual polish.
"""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
from .contracts import ArtifactReceipt


def verify_artifact(path: Path, kind: str, max_bytes: int=50_000_000) -> ArtifactReceipt:
    path=Path(path)
    if not path.is_file() or path.stat().st_size < 10 or path.stat().st_size > max_bytes:
        raise ValueError('Missing, empty or oversized artifact')
    data=path.read_bytes()
    if kind=='pdf':
        if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-2048:]:
            raise ValueError('Malformed PDF signature or missing EOF')
    elif kind in ('docx','pptx','xlsx','zip'):
        if not zipfile.is_zipfile(path):raise ValueError('Invalid ZIP-based document')
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:raise ValueError('Bad archive CRC')
            names=set(z.namelist())
            must={'docx':'word/document.xml','pptx':'ppt/presentation.xml','xlsx':'xl/workbook.xml'}.get(kind)
            if must and must not in names:raise ValueError(f'Missing {must}')
            if kind=='pptx' and not any(n.startswith('ppt/slides/slide') and n.endswith('.xml') for n in names):
                raise ValueError('No presentation slides')
    elif kind=='png':
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Invalid PNG')
    elif kind=='svg':
        if ET.fromstring(data).tag.rsplit('}',1)[-1]!='svg':raise ValueError('Invalid SVG')
    elif kind=='json':
        json.loads(data.decode('utf-8'))
    elif kind=='csv':
        content=data.decode('utf-8-sig'); rows=list(csv.reader(content.splitlines()))
        if not rows or not rows[0] or any(len(r)!=len(rows[0]) for r in rows):
            raise ValueError('Invalid CSV columns')
    elif kind in ('md','txt','html'):
        if not data.decode('utf-8').strip():raise ValueError('Empty text')
        if kind=='html' and '<html' not in data.decode('utf-8').lower():raise ValueError('Missing HTML document root')
    else:
        raise ValueError('Unsupported verification type')
    return ArtifactReceipt(kind=kind,name=path.name,sha256=hashlib.sha256(data).hexdigest(),byte_size=len(data),verified=True).validate()
