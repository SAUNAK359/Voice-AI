"""V14 streaming ingestion integration tests — no provider or GPU required."""
from __future__ import annotations
import hashlib
import io
import sqlite3
from pathlib import Path
import tempfile
import unittest
import zipfile

from rizzler.source_large import LargeSourceTransfers, MAX_BYTES, CHUNK_BYTES
from rizzler.source_index import SourceIndex

class StreamingSources(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.transfer=LargeSourceTransfers(self.tmp.name)
        self.index=SourceIndex(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def receive(self,owner,name,payload):
        transfer=self.transfer.start(owner,name,len(payload),hashlib.sha256(payload).hexdigest())
        chunk=CHUNK_BYTES
        for offset in range(0,len(payload),chunk):
            body=payload[offset:offset+chunk]
            result=self.transfer.append(owner,transfer["id"],offset,body,hashlib.sha256(body).hexdigest())
            self.assertEqual(result["offset"],offset+len(body))
        return transfer
    def test_200mb_capacity(self):
        self.assertEqual(MAX_BYTES,200_000_000)
        with self.assertRaises(ValueError):
            self.transfer.start("u","x.txt",MAX_BYTES+1,"")
        item=self.transfer.start("u","x.txt",MAX_BYTES,"")
        self.assertEqual(item["bytes"],200_000_000)
    def test_full_coverage_beyond_old_truncation(self):
        data=(("Key analytical evidence in the last segment.\n"*60000).encode())
        t=self.receive("analyst","large.txt",data)
        result=self.transfer.finalize("analyst",t["id"],self.index)
        self.assertGreater(result["metadata"]["extracted_bytes"],1_500_000)
        self.assertEqual(result["bytes"],len(data))
        self.assertGreater(result["passages"],900)
        count=self.index.search("analyst",[t["id"]],"analytical evidence")
        self.assertEqual(count["indexed"],result["passages"])
        self.assertEqual(self.transfer.get("analyst",t["id"])["state"],"complete")
    def test_chunk_order_replay_and_tamper(self):
        data=b"abc\ndef\n"
        t=self.transfer.start("owner","a.md",len(data),"")
        with self.assertRaises(ValueError):
            self.transfer.append("owner",t["id"],1,data,hashlib.sha256(data).hexdigest())
        digest=hashlib.sha256(data).hexdigest()
        self.transfer.append("owner",t["id"],0,data,digest)
        self.assertTrue(self.transfer.append("owner",t["id"],0,data,digest)["replayed"])
        with self.assertRaises(ValueError):
            self.transfer.append("owner",t["id"],0,b"x",hashlib.sha256(b"x").hexdigest())
        with self.assertRaises(ValueError):
            self.transfer.get("another",t["id"])
    def test_failed_full_digest_cannot_publish(self):
        t=self.transfer.start("owner","a.txt",4,"0"*64)
        self.transfer.append("owner",t["id"],0,b"abcd",hashlib.sha256(b"abcd").hexdigest())
        with self.assertRaises(ValueError):
            self.transfer.finalize("owner",t["id"],self.index)
        self.assertEqual(self.index.list("owner"),[])
    def test_sqlite_complete_table_content(self):
        path=Path(self.tmp.name)/"demo.db"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE sales (id INTEGER, amount INTEGER)")
            conn.executemany("INSERT INTO sales VALUES (?,?)",[(i,i*11) for i in range(120)])
        payload=path.read_bytes()
        t=self.receive("owner","sales.db",payload)
        result=self.transfer.finalize("owner",t["id"],self.index)
        self.assertGreater(result["passages"],0)
        records=self.index.search("owner",[t["id"]],"sales")
        self.assertEqual(records["coverage"],"retrieved_excerpts_only")
    def test_unsafe_office_archive_refused(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,"w") as z:
            z.writestr("word/document.xml","<document><t>test</t></document>")
            z.writestr("word/../payload.exe",b"bad")
        payload=raw.getvalue()
        t=self.receive("owner","sample.docx",payload)
        with self.assertRaises(ValueError):
            self.transfer.finalize("owner",t["id"],self.index)
        self.assertEqual(self.index.list("owner"),[])

if __name__=="__main__":unittest.main()
