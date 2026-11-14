"""Bounded, owner-scoped source indexing for documents and datasets.

Files are parsed once, not inserted wholesale into the Live LLM context.
Each excerpt carries a stable source reference; no arbitrary SQL or macros run.
"""
from __future__ import annotations
import csv, hashlib, io, json, re, secrets, sqlite3, time, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ALLOWED={".txt",".md",".json",".csv",".xlsx",".docx",".pptx",".pdf",".db",".sqlite",".sqlite3"}
MAX_BYTES=8_000_000
CHUNK_SIZE=1800
MAX_TEXT=1_500_000

def _xml_text(z, path):
    root=ET.fromstring(z.read(path))
    return " ".join(t.text.strip() for t in root.iter() if t.tag.rsplit('}',1)[-1] in ("t","v") and t.text and t.text.strip())

def extract(name:str,data:bytes)->tuple[str,dict]:
    extension=Path(name).suffix.lower()
    if extension not in ALLOWED:raise ValueError("Unsupported document type")
    if not 1<=len(data)<=MAX_BYTES:raise ValueError("Source exceeds 8 MB ingestion limit")
    if extension in (".txt",".md",".json",".csv"):
        text=data.decode("utf-8-sig",errors="strict")
        if extension==".json":json.loads(text)
        if extension==".csv":
            rows=csv.reader(io.StringIO(text));header=next(rows,None)
            if not header or len(header)>100:raise ValueError("Invalid CSV columns")
            text="Columns: "+", ".join(header)+"\n"+"\n".join(", ".join(row) for _,row in zip(range(30000),rows))
        return text[:MAX_TEXT],{"kind":extension[1:]}
    if extension in (".db",".sqlite",".sqlite3"):
        if not data.startswith(b"SQLite format 3\x00"):raise ValueError("Invalid SQLite header")
        # Work only on a temporary database copy in query-only mode.
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"source.db";p.write_bytes(data)
            con=sqlite3.connect(f"file:{p}?mode=ro&immutable=1",uri=True)
            try:
                con.execute("PRAGMA query_only=ON")
                con.execute("PRAGMA trusted_schema=OFF")
                if con.execute("PRAGMA quick_check(1)").fetchone()[0]!="ok":raise ValueError("Database integrity failure")
                rows=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 50").fetchall()
                parts=[]
                for (table,) in rows:
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,100}",table):continue
                    info=con.execute(f'PRAGMA table_info("{table}")').fetchall()
                    columns=[str(x[1]) for x in info[:50]]
                    parts.append(f"Table {table} columns: "+", ".join(columns))
                    try:
                        samples=con.execute(f'SELECT * FROM "{table}" LIMIT 5').fetchall()
                        parts.extend(str(tuple(str(v)[:120] for v in row)) for row in samples)
                    except sqlite3.DatabaseError:continue
                return "\n".join(parts)[:MAX_TEXT],{"kind":"sqlite","tables":len(rows),"sampling":"read_only"}
            finally:con.close()
    if extension==".pdf":
        try:import fitz
        except ImportError:raise ValueError("PDF text extraction requires PyMuPDF") from None
        doc=fitz.open(stream=data,filetype="pdf")
        try:
            if doc.needs_pass:raise ValueError("Encrypted PDFs require a password-handling flow")
            if len(doc)>2000:raise ValueError("PDF page count exceeds source indexing limit")
            parts=[]
            for page in doc:
                parts.append(f"[Page {page.number+1}]\n"+page.get_text("text",sort=True))
                if sum(len(s) for s in parts)>MAX_TEXT:break
            return "\n".join(parts)[:MAX_TEXT],{"kind":"pdf","pages":len(doc),"note":"Text extraction only; image-only pages need visual OCR/indexing"}
        finally:doc.close()
    if not zipfile.is_zipfile(io.BytesIO(data)):raise ValueError("Invalid Office document archive")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info=z.infolist()
        if len(info)>1500 or sum(x.file_size for x in info)>70_000_000:raise ValueError("Unsafe inflated Office archive")
        for x in info:
            path=x.filename.replace("\\","/")
            if path.startswith("/") or ".." in path.split("/") or x.filename.lower().endswith((".exe",".dll","vbaproject.bin")) or (x.external_attr>>16)&0o170000==0o120000:
                raise ValueError("Unsafe archive entry")
        if z.testzip() is not None:raise ValueError("Corrupt Office document")
        names=set(z.namelist())
        if extension==".docx":
            if "word/document.xml" not in names:raise ValueError("Invalid Word document")
            parts=[_xml_text(z,"word/document.xml")]
        elif extension==".pptx":
            slides=sorted((p for p in names if re.fullmatch(r"ppt/slides/slide\d+\.xml",p)),key=lambda p:int(re.search(r"slide(\d+)",p).group(1)))
            if not slides:raise ValueError("No slides in presentation")
            parts=[f"[Slide {i+1}]\n"+_xml_text(z,p) for i,p in enumerate(slides)]
        else:
            if "xl/workbook.xml" not in names:raise ValueError("Invalid workbook")
            try:
                import openpyxl
                book=openpyxl.load_workbook(io.BytesIO(data),read_only=True,data_only=True)
                try:
                    parts=[]
                    extracted_size=0
                    for sheet in book.worksheets[:30]:
                        parts.append(f"[Sheet {sheet.title}]")
                        for idx,row in enumerate(sheet.iter_rows(values_only=True)):
                            if idx>=10000:break
                            line=" | ".join(str(v)[:150] if v is not None else "" for v in row[:80])
                            parts.append(line)
                            extracted_size+=len(line)
                            if extracted_size>MAX_TEXT:break
                finally:book.close()
            except ImportError:raise ValueError("Excel indexing requires openpyxl") from None
        return "\n".join(parts)[:MAX_TEXT],{"kind":extension[1:]}

def chunks(text):
    # Preserve document order and evidence offsets; no token-level truncation of entire input.
    blocks=[];start=0
    while start<len(text):
        end=min(start+CHUNK_SIZE,len(text))
        if end<len(text):
            split=text.rfind("\n",start+CHUNK_SIZE//2,end)
            if split>start:end=split+1
        blocks.append((start,text[start:end]))
        start=end
    return blocks

class SourceIndex:
    def __init__(self,root):
        self.root=Path(root).resolve()/"source_index";self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=self.root/"sources.sqlite3"
        with sqlite3.connect(self.db) as db:
            had_fts=bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='passage_fts'").fetchone())
            db.executescript("""CREATE TABLE IF NOT EXISTS sources(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT NOT NULL,
                sha256 TEXT NOT NULL,bytes INT NOT NULL,kind TEXT NOT NULL,
                metadata TEXT NOT NULL,created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS sources_owner ON sources(owner,created);
                CREATE TABLE IF NOT EXISTS chunks(
                source_id TEXT NOT NULL,number INT NOT NULL,position INT NOT NULL,
                body TEXT NOT NULL,PRIMARY KEY(source_id,number));
                CREATE INDEX IF NOT EXISTS passage_source ON chunks(source_id,number);
                CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(body,content='chunks',content_rowid='rowid');
                CREATE TRIGGER IF NOT EXISTS passage_insert AFTER INSERT ON chunks BEGIN
                    INSERT INTO passage_fts(rowid,body) VALUES(new.rowid,new.body);
                END;
                CREATE TRIGGER IF NOT EXISTS passage_delete AFTER DELETE ON chunks BEGIN
                    INSERT INTO passage_fts(passage_fts,rowid,body) VALUES('delete',old.rowid,old.body);
                END;""")
            if not had_fts and db.execute(
                "SELECT count(*) FROM chunks").fetchone()[0]>0:
                db.execute("INSERT INTO passage_fts(passage_fts) VALUES('rebuild')")
    def register(self,owner,name,data,source_url=None):
        from .security import safe_upload_name
        safe_upload_name(name,allowed=ALLOWED)
        digest=hashlib.sha256(data).hexdigest()
        text,meta=extract(name,data)
        if source_url is not None:
            if not isinstance(source_url,str) or not source_url.startswith("https://") or len(source_url)>2000:
                raise ValueError("Invalid source URL provenance")
            meta["source_url"]=source_url
        if not text.strip():raise ValueError("Document contains no extractable text; use visual PDF indexing")
        parts=chunks(text)
        if len(parts)>900:raise ValueError("Source index exceeds bounded passage limit")
        with sqlite3.connect(self.db,timeout=15) as db:
            n=db.execute("SELECT COUNT(*) FROM sources WHERE owner=?",(owner,)).fetchone()[0]
            if n>=30:raise ValueError("Source limit reached")
            uid=secrets.token_hex(16)
            db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
                       (uid,owner,name,digest,len(data),meta["kind"],json.dumps(meta),time.time()))
            db.executemany("INSERT INTO chunks VALUES(?,?,?,?)",[(uid,i,pos,body) for i,(pos,body) in enumerate(parts)])
        return {"id":uid,"name":name,"bytes":len(data),"passages":len(parts),"metadata":meta}
    def list(self,owner):
        with sqlite3.connect(self.db) as db:
            rows=db.execute("SELECT id,name,bytes,kind,metadata FROM sources WHERE owner=? ORDER BY created DESC LIMIT 30",(owner,)).fetchall()
        return [{"id":i,"name":name,"bytes":n,"kind":kind,"metadata":json.loads(meta)} for i,name,n,kind,meta in rows]
    def search(self,owner,ids,query,max_chars=9000):
        """Owner-scoped, indexed retrieval; complete coverage is a separate Work operation."""
        if type(ids) is not list or not ids or len(ids)>8 or len(set(ids))!=len(ids):
            raise ValueError("Select 1–8 distinct owned sources")
        if not isinstance(query,str) or len(query)>8000 or not 100<=max_chars<=18000:
            raise ValueError("Invalid retrieval budget")
        with sqlite3.connect(self.db,timeout=30) as db:
            records=db.execute("SELECT id,name FROM sources WHERE owner=?",(owner,)).fetchall()
            names=dict(records)
            if not set(ids).issubset(names):raise PermissionError("Unowned source reference")
            count=db.execute("SELECT count(*) FROM chunks WHERE source_id IN ("+
                             ",".join("?" for _ in ids)+")",ids).fetchone()[0]
            stop={"the","and","with","from","that","this","into","for","you","your","what","how","please","create","make","generate","report","summary"}
            terms=list(dict.fromkeys(x for x in re.findall(r"\w{3,}",query.lower())
                                     if x not in stop))[:12]
            selected=[]
            if terms:
                expression=" OR ".join('"'+t.replace('"','')+'"' for t in terms)
                try:
                    q=("SELECT c.source_id,c.number,c.position,c.body FROM passage_fts "
                       "JOIN chunks c ON passage_fts.rowid=c.rowid WHERE passage_fts MATCH ? "
                       "AND c.source_id IN ("+",".join("?" for _ in ids)+") "
                       "ORDER BY bm25(passage_fts) LIMIT 18")
                    selected=db.execute(q,[expression,*ids]).fetchall()
                except sqlite3.OperationalError:
                    selected=[]
            if not selected:
                # A query without matching terms must not pretend to cover the
                # whole file; sample the beginning and end explicitly.
                for uid in ids:
                    selected.extend(db.execute(
                        "SELECT source_id,number,position,body FROM chunks WHERE source_id=? "
                        "ORDER BY number LIMIT 3",(uid,)).fetchall())
                    selected.extend(db.execute(
                        "SELECT source_id,number,position,body FROM chunks WHERE source_id=? "
                        "ORDER BY number DESC LIMIT 2",(uid,)).fetchall())
        output=[];used=0
        for uid,number,pos,body in selected:
            excerpt=f"[Source {names[uid]} / {uid} / passage {number+1} / offset {pos}]\n"+body+"\n"
            if used+len(excerpt)>max_chars:break
            output.append(excerpt);used+=len(excerpt)
        return {"passages":output,"indexed":count,"returned":len(output),
                "coverage":"retrieved_excerpts_only"}
