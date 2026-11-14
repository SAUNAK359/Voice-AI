"""V13 source-index, owner isolation, queue fairness and frontend contracts."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rizzler.source_index import SourceIndex, extract
from rizzler.work_store import WorkStore

class SourceIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.index=SourceIndex(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def test_text_retrieval_and_owner_isolation(self):
        text=("Inventory turnover improved because warehouses switched to demand forecasts.\n"*60).encode()
        item=self.index.register("owner_one","inventory.md",text)
        found=self.index.search("owner_one",[item["id"]],"What improved inventory turnover?")
        self.assertGreater(found["returned"],0)
        self.assertIn("inventory.md",found["passages"][0])
        with self.assertRaises(PermissionError):
            self.index.search("owner_two",[item["id"]],"inventory")
        self.assertEqual(self.index.list("owner_two"),[])
    def test_rejects_unsupported_and_unsafe_inputs(self):
        with self.assertRaises(ValueError):self.index.register("owner","../file.md",b"hello")
        with self.assertRaises(ValueError):self.index.register("owner","script.exe",b"hello")
        with self.assertRaises(ValueError):extract("wrong.json",b"{invalid")
        with self.assertRaises(ValueError):extract("bad.db",b"not a database")
    def test_sqlite_inspects_without_modifying_data(self):
        p=Path(self.temp.name)/"sample.db"
        with sqlite3.connect(p) as db:
            db.execute("CREATE TABLE inventory (sku TEXT, stock INTEGER)")
            db.execute("INSERT INTO inventory VALUES ('A1',42)")
        raw=p.read_bytes()
        extracted,meta=extract("inventory.sqlite",raw)
        self.assertIn("inventory",extracted)
        self.assertIn("stock",extracted)
        self.assertEqual(meta["sampling"],"read_only")
        self.assertEqual(raw,p.read_bytes())

class QueueIsolationTests(unittest.TestCase):
    def test_one_active_job_per_owner_even_with_multiple_workers(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{"RIZZLER_AGENTIC_ENABLED":"1"}):
            store=WorkStore(d)
            first=store.submit("owner_one","Build a verified presentation",["pptx"],"first_job_001",[])
            second=store.submit("owner_one","Build an inventory summary",["md"],"second_job_001",[])
            other=store.submit("owner_two","Generate a short report",["md"],"other_job_001",[])
            claimed=store.claim("worker_A",lease_seconds=60)
            self.assertEqual(claimed["id"],first["id"])
            claimed_2=store.claim("worker_B",lease_seconds=60)
            self.assertEqual(claimed_2["id"],other["id"])
            self.assertEqual(store.get("owner_one",second["id"])["status"],"queued")
            self.assertIsNone(store.claim("worker_C",lease_seconds=60))

class StudioContractTests(unittest.TestCase):
    def test_desktop_layout_and_attachment_control_present(self):
        root=Path(__file__).resolve().parents[1]/"src"/"rizzler"/"web"
        html=(root/"index.html").read_text(encoding="utf-8")
        css=(root/"style.css").read_text(encoding="utf-8")
        js=(root/"studio.js").read_text(encoding="utf-8")
        for identifier in ('id="workspace-files"','id="studio-preview"','id="studio-progress"',
                           'id="studio-job-select"','id="agent-text"'):
            self.assertIn(identifier,html)
        self.assertIn("overflow-y:auto",css)
        self.assertIn("api/source/selection",js)
        self.assertIn("api/work/sources",js)
        self.assertNotIn('<form id="link-entry"',html)

if __name__=="__main__":unittest.main()
