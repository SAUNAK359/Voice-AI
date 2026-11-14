"""200 MB resumable source transfer and bounded-memory full-file indexing.

Input is handled in fixed-size chunks. The original file and every indexed
passage remain identifiable; nothing silently drops a trailing portion.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_BYTES = 200_000_000
CHUNK_BYTES = 1_000_000
MAX_EXTRACTED_BYTES = 1_000_000_000
MAX_CHUNKS = 650_000

def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            h.update(block)
    return h.hexdigest()

def _zip_guard(path):
    archive = zipfile.ZipFile(path)
    entries = archive.infolist()
    if len(entries) > 15_000 or sum(x.file_size for x in entries) > MAX_EXTRACTED_BYTES:
        archive.close()
        raise ValueError("Expanded Office document exceeds safety budget")
    for entry in entries:
        parts = entry.filename.replace("\\", "/").split("/")
        if (entry.filename.startswith("/") or ".." in parts or
            entry.filename.lower().endswith(("vbaproject.bin",".exe",".dll")) or
            (entry.external_attr >> 16) & 0o170000 == 0o120000):
            archive.close()
            raise ValueError("Unsafe Office archive entry")
    if archive.testzip() is not None:
        archive.close()
        raise ValueError("Damaged Office archive")
    return archive

def _xml_fragments(stream):
    for _, element in ET.iterparse(stream, events=("end",)):
        if element.tag.rsplit("}", 1)[-1] in ("t", "v") and element.text:
            yield element.text
        element.clear()

def _extract_segments(path, name):
    suffix=Path(name).suffix.lower()
    if suffix in (".txt",".md",".json"):
        with path.open("r",encoding="utf-8-sig",errors="strict") as source:
            yield from source
        return
    if suffix==".csv":
        with path.open("r",encoding="utf-8-sig",newline="") as source:
            for row in csv.reader(source):
                if len(row)>500:
                    raise ValueError("Too many CSV columns")
                yield " | ".join(str(x) for x in row)+"\n"
        return
    if suffix in (".db",".sqlite",".sqlite3"):
        with path.open("rb") as source:
            if source.read(16)!=b"SQLite format 3\x00":
                raise ValueError("Invalid SQLite database")
        db=sqlite3.connect("file:"+str(path)+"?mode=ro&immutable=1",uri=True)
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            if db.execute("PRAGMA quick_check(1)").fetchone()[0]!="ok":
                raise ValueError("Database integrity check failed")
            tables=[row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            for table in tables:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,100}",table):
                    raise ValueError("Unsupported SQLite table identifier")
                yield "[Table "+table+"]\n"
                columns=[x[1] for x in db.execute('PRAGMA table_info("'+table+'")')]
                yield " | ".join(columns)+"\n"
                for row in db.execute('SELECT * FROM "'+table+'"'):
                    yield " | ".join(str(value)[:2000] if value is not None else "" for value in row)+"\n"
        finally:
            db.close()
        return
    if suffix==".pdf":
        try: import fitz
        except ImportError as exc: raise RuntimeError("Install PyMuPDF for PDF indexing") from exc
        doc=fitz.open(str(path))
        try:
            if doc.needs_pass: raise ValueError("Password protected PDF is unsupported")
            for page in doc:
                text=page.get_text("text",sort=True)
                if not text.strip():
                    yield "[Page "+str(page.number+1)+": visual extraction required]\n"
                else:
                    yield "[Page "+str(page.number+1)+"]\n"+text+"\n"
        finally: doc.close()
        return
    if suffix in (".docx",".pptx",".xlsx"):
        with _zip_guard(path) as z:
            names=set(z.namelist())
            if suffix==".docx":
                if "word/document.xml" not in names: raise ValueError("Word document is invalid")
                with z.open("word/document.xml") as source:
                    for fragment in _xml_fragments(source): yield fragment+"\n"
            elif suffix==".pptx":
                slides=sorted((n for n in names if re.fullmatch(r"ppt/slides/slide[0-9]+\.xml",n)),
                    key=lambda n:int(re.search(r"slide(\d+)",n).group(1)))
                if not slides: raise ValueError("Presentation contains no slides")
                for n,slide in enumerate(slides,1):
                    yield "[Slide "+str(n)+"]\n"
                    with z.open(slide) as source:
                        for fragment in _xml_fragments(source): yield fragment+"\n"
            else:
                if "xl/workbook.xml" not in names: raise ValueError("Workbook is invalid")
                try: import openpyxl
                except ImportError as exc: raise RuntimeError("Install openpyxl for Excel indexing") from exc
                workbook=openpyxl.load_workbook(path,read_only=True,data_only=False)
                try:
                    for sheet in workbook:
                        yield "[Sheet "+sheet.title+"]\n"
                        for row in sheet.iter_rows(values_only=True):
                            yield " | ".join(str(cell)[:3000] if cell is not None else "" for cell in row)+"\n"
                finally: workbook.close()
        return
    raise ValueError("Unsupported file type")

def index_large(index, owner, name, path, uid):
    """Atomic indexing with stable source ID; replay of a finalized upload is safe."""
    from .security import safe_upload_name
    from .source_index import ALLOWED, CHUNK_SIZE
    safe_upload_name(name, allowed=ALLOWED)
    path=Path(path).resolve()
    size=path.stat().st_size
    if not 1<=size<=MAX_BYTES:raise ValueError("Invalid source size")
    digest=_sha256(path)
    with sqlite3.connect(index.db, timeout=120) as db:
        db.execute("BEGIN IMMEDIATE")
        existing=db.execute("SELECT id,owner,name FROM sources WHERE id=?",(uid,)).fetchone()
        if existing:
            if existing[1]!=owner or existing[2]!=name:raise ValueError("Source receipt mismatch")
            count=db.execute("SELECT count(*) FROM chunks WHERE source_id=?",(uid,)).fetchone()[0]
            return {"id":uid,"name":name,"bytes":size,"passages":count,"replayed":True}
        if db.execute("SELECT count(*) FROM sources WHERE owner=?",(owner,)).fetchone()[0]>=30:
            raise ValueError("Source quota exceeded")
        position=0; n=0; buffer=""; extracted=0; batch=[]
        for text in _extract_segments(path,name):
            if not isinstance(text,str):raise ValueError("Invalid extracted text")
            extracted+=len(text.encode("utf-8"))
            if extracted>MAX_EXTRACTED_BYTES:raise ValueError("Expanded source exceeds indexing budget")
            buffer+=text
            while len(buffer)>=CHUNK_SIZE:
                piece,buffer=buffer[:CHUNK_SIZE],buffer[CHUNK_SIZE:]
                batch.append((uid,n,position,piece));position+=len(piece);n+=1
                if n>MAX_CHUNKS:raise ValueError("Too many indexed passages")
                if len(batch)>=500:
                    db.executemany("INSERT INTO chunks VALUES(?,?,?,?)",batch);batch.clear()
        if buffer:
            batch.append((uid,n,position,buffer));n+=1
        if not n:raise ValueError("File contains no extractable text")
        if batch:db.executemany("INSERT INTO chunks VALUES(?,?,?,?)",batch)
        metadata={"kind":Path(name).suffix[1:].lower(),"coverage":"all_extracted_text",
                  "extracted_bytes":extracted,"passages":n,
                  "visual_qa_required":Path(name).suffix.lower() in (".pdf",".pptx",".docx")}
        db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
            (uid,owner,name,digest,size,metadata["kind"],json.dumps(metadata),time.time()))
    return {"id":uid,"name":name,"bytes":size,"passages":n,"metadata":metadata}

class LargeSourceTransfers:
    def __init__(self,root):
        self.root=Path(root).resolve()/"large_source_transfers"
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=self.root/"transfers.sqlite3"
        with sqlite3.connect(self.db,timeout=30) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS transfers(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT NOT NULL,size INTEGER NOT NULL,
                sha TEXT NOT NULL,received INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'uploading',source_id TEXT,created REAL NOT NULL)""")
    def _path(self,owner,uid):
        dirname=hashlib.sha256(owner.encode()).hexdigest()
        directory=self.root/dirname
        directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        return directory/(uid+".upload")
    def start(self,owner,name,size,sha):
        from .security import safe_upload_name
        from .source_index import ALLOWED
        safe_upload_name(name,allowed=ALLOWED)
        if type(size) is not int or not 1<=size<=MAX_BYTES:raise ValueError("Source size outside 200 MB limit")
        if not isinstance(sha,str) or (sha and not re.fullmatch("[a-f0-9]{64}",sha)):raise ValueError("Invalid SHA-256")
        with sqlite3.connect(self.db,timeout=30) as db:
            n=db.execute("SELECT count(*) FROM transfers WHERE owner=? AND state IN ('uploading','indexing')",
                         (owner,)).fetchone()[0]
            if n>=3:raise ValueError("Too many concurrent uploads")
            uid=secrets.token_hex(16)
            db.execute("INSERT INTO transfers(id,owner,name,size,sha,created) VALUES(?,?,?,?,?,?)",
                      (uid,owner,name,size,sha,time.time()))
        return {"id":uid,"name":name,"bytes":size,"offset":0,"chunk_size":CHUNK_BYTES}
    def get(self,owner,uid):
        if not re.fullmatch("[a-f0-9]{32}",uid):raise ValueError("Invalid upload ID")
        with sqlite3.connect(self.db) as db:
            row=db.execute("SELECT id,name,size,received,state,source_id FROM transfers WHERE owner=? AND id=?",
                           (owner,uid)).fetchone()
        if not row:raise ValueError("Upload not found")
        return dict(zip(("id","name","bytes","offset","state","source_id"),row))
    def append(self,owner,uid,offset,blob,digest):
        if not isinstance(blob,bytes) or not 1<=len(blob)<=CHUNK_BYTES:raise ValueError("Invalid upload chunk")
        if type(offset) is not int or offset<0 or hashlib.sha256(blob).hexdigest()!=digest:
            raise ValueError("Invalid chunk checksum or offset")
        with sqlite3.connect(self.db,timeout=40) as db:
            db.execute("BEGIN IMMEDIATE")
            rec=db.execute("SELECT size,received,state FROM transfers WHERE owner=? AND id=?",(owner,uid)).fetchone()
            if not rec or rec[2]!="uploading":raise ValueError("Upload unavailable")
            total,received=rec[:2]
            if offset<received and offset+len(blob)<=received:
                with self._path(owner,uid).open("rb") as f:
                    f.seek(offset)
                    if f.read(len(blob))!=blob:raise ValueError("Conflicting previously accepted chunk")
                return {"offset":received,"replayed":True}
            if offset!=received or received+len(blob)>total:raise ValueError("Chunk out of sequence")
            path=self._path(owner,uid)
            with path.open("r+b" if path.exists() else "w+b") as f:
                f.seek(received)
                f.truncate()
                f.write(blob);f.flush();os.fsync(f.fileno())
            received+=len(blob)
            db.execute("UPDATE transfers SET received=? WHERE id=?",(received,uid))
        return {"offset":received,"complete":received==total}
    def finalize(self,owner,uid,index,scanner=None):
        with sqlite3.connect(self.db,timeout=40) as db:
            db.execute("BEGIN IMMEDIATE")
            rec=db.execute("SELECT name,size,sha,received,state FROM transfers WHERE id=? AND owner=?",
                           (uid,owner)).fetchone()
            if not rec:raise ValueError("Transfer unavailable")
            name,total,sha,received,state=rec
            if state=="complete":return self.get(owner,uid)
            if state!="uploading" or total!=received:raise ValueError("Incomplete upload")
            db.execute("UPDATE transfers SET state='indexing' WHERE id=?",(uid,))
        try:
            path=self._path(owner,uid)
            if path.stat().st_size!=total or (sha and _sha256(path)!=sha):raise ValueError("Source checksum mismatch")
            if scanner is not None:scanner(path)
            item=index_large(index,owner,name,path,uid)
        except BaseException:
            with sqlite3.connect(self.db) as db:
                db.execute("UPDATE transfers SET state='uploading' WHERE id=? AND owner=?",(uid,owner))
            raise
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE transfers SET state='complete',source_id=? WHERE id=? AND owner=?",
                       (item["id"],uid,owner))
        return item
