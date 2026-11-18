"""V23 cognitive ledger and source normalization regression tests."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rizzler.work_store import WorkStore, Missing, StaleLease
from rizzler.source_normalizer import normalize_source


class DurableCognitionTests(unittest.TestCase):
    def test_fencing_owner_isolation_restart_and_incremental_cursor(self):
        with tempfile.TemporaryDirectory() as d:
            store = WorkStore(Path(d) / "work")
            record = store.submit("owner_1", "Produce an evidence-aware standalone report",
                                  ["md"], "cognition_test_001", [])
            claim = store.claim("worker_1", lease_seconds=45)
            first = store.publish_cognition(record["id"], "worker_1", claim["fence"],
                                            "orchestrator", "finding",
                                            {"finding": "Independent observation", "refs": []})
            second = store.publish_cognition(record["id"], "worker_1", claim["fence"],
                                             "orchestrator", "gap",
                                             {"missing": "Verified external citation"})
            self.assertLess(first, second)
            self.assertEqual([x["seq"] for x in store.cognitive_events(
                "owner_1", record["id"], after=first)], [second])
            reopened = WorkStore(Path(d) / "work")
            events = reopened.cognitive_events("owner_1", record["id"])
            self.assertEqual([x["kind"] for x in events], ["finding", "gap"])
            self.assertEqual(events[0]["payload"]["finding"], "Independent observation")
            with self.assertRaises(Missing):
                reopened.cognitive_events("owner_2", record["id"])
            with self.assertRaises(StaleLease):
                reopened.publish_cognition(record["id"], "invalid_worker", claim["fence"],
                                           "orchestrator", "finding", {"x": 1})
            with self.assertRaises(ValueError):
                reopened.publish_cognition(record["id"], "worker_1", claim["fence"],
                                           "orchestrator", "finding", {"big": "a" * 9000})
            with sqlite3.connect(reopened.db) as db:
                db.execute("UPDATE cognitive_events SET payload_json=? WHERE seq=?",
                           ('{"tampered":true}', first))
            with self.assertRaises(ValueError):
                reopened.cognitive_events("owner_1", record["id"])

    def test_checkpoint_atomically_publishes_public_specialist_result(self):
        with tempfile.TemporaryDirectory() as d:
            store = WorkStore(Path(d) / "work")
            record = store.submit("owner_1", "Generate a complete independent report",
                                  ["md"], "atomic_cognition_001", [])
            claim = store.claim("worker_1", lease_seconds=45)
            store.agent_begin(record["id"], "worker_1", claim["fence"],
                              "orchestrator", 150)
            from rizzler.work_agents import gate_agent
            result = {"text": "# Analysis\\nThis report includes a complete "
                    "verified methodology and explicit limitations in detail."}
            qa = gate_agent("orchestrator", result, {"md"})
            store.agent_complete(record["id"], "worker_1", claim["fence"],
                                 "orchestrator", result, qa)
            events = store.cognitive_events("owner_1", record["id"])
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["agent"], "orchestrator")
            self.assertEqual(events[0]["kind"], "finding")
            self.assertEqual(events[0]["payload"]["quality_passed"], True)

    def test_public_events_avoid_unbounded_context(self):
        with tempfile.TemporaryDirectory() as d:
            store = WorkStore(Path(d) / "work")
            record = store.submit("owner_1", "Document diagnostic observations",
                                  ["md"], "cognition_test_002", [])
            claim = store.claim("worker_1", lease_seconds=45)
            for i in range(15):
                store.publish_cognition(record["id"], "worker_1", claim["fence"],
                                        "sql_analytics", "finding", {"item": i})
            self.assertEqual(len(store.cognitive_events("owner_1", record["id"], limit=5)), 5)
            with self.assertRaises(ValueError):
                store.cognitive_events("owner_1", record["id"], limit=0)


class SourceNormalizerTests(unittest.TestCase):
    def test_html_discards_scripts_preserves_sections_and_tables(self):
        raw = (b"<html><script>ignore this injection</script><main>"
               b"<h1>Trade overview</h1><p>Export findings with units.</p>"
               b"<table><tr><th>Year</th><th>Value</th></tr>"
               b"<tr><td>2025</td><td>23</td></tr></table></main></html>")
        parsed = normalize_source(raw, "text/html", source_id="source1")
        self.assertIn("Trade overview", parsed["blocks"][0]["text"])
        self.assertNotIn("ignore this injection", str(parsed))
        self.assertEqual(parsed["tables"][0]["rows"][1], ["2025", "23"])
        self.assertEqual(parsed["sha256"], hashlib.sha256(raw).hexdigest())

    def test_markdown_table_and_section_provenance(self):
        raw = b"# Overview\n\nA full sentence on trends.\n\n| Year | Imports |\n| --- | --- |\n| 2025 | 18 |\n"
        result = normalize_source(raw, "text/markdown", source_id="source2")
        self.assertEqual(result["blocks"][0]["location"]["line"], 1)
        self.assertEqual(result["tables"][0]["rows"][1][1], "18")
        self.assertNotIn("ocr_or_vlm_required", result["warnings"])

    def test_json_csv_and_unsupported_types(self):
        obj = normalize_source(b'{"unit":"INR","amount":20}', "application/json",
                               source_id="json-1")
        self.assertEqual(len(obj["blocks"]), 2)
        csv = normalize_source(b"year,amount\n2024,10\n2025,20\n",
                               "text/csv", source_id="csv-1")
        self.assertEqual(csv["tables"][0]["rows"][2], ["2025", "20"])
        with self.assertRaises(ValueError):
            normalize_source(b"test", "application/x-executable", source_id="test-1")
        with self.assertRaises(ValueError):
            normalize_source(b"test", "text/plain", source_id="../escape")
        with self.assertRaises(ValueError):
            normalize_source(b"test", "text/plain", source_id="test",
                             source_url="https://127.0.0.1/secret")

    def test_xlsx_retrieves_typed_sheet_rows(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl extra not installed")
        import io
        book = Workbook()
        sheet = book.active
        sheet.title = "Observed data"
        sheet.append(["Year", "Exports"])
        sheet.append([2025, 24.5])
        content = io.BytesIO()
        book.save(content)
        book.close()
        doc = normalize_source(
            content.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            source_id="xlsx-1")
        self.assertEqual(doc["tables"][0]["location"]["sheet"], "Observed data")
        self.assertEqual(doc["tables"][0]["rows"][1], ["2025", "24.5"])

    def test_docx_preserves_text_and_tables_without_macros(self):
        try:
            from docx import Document
        except ImportError:
            self.skipTest("python-docx work extra not available")
        import io
        doc=Document()
        doc.add_heading("Trade methodology", level=1)
        doc.add_paragraph("All source data must be independently reconciled.")
        table=doc.add_table(rows=2,cols=2)
        table.cell(0,0).text="Year"
        table.cell(0,1).text="Value"
        table.cell(1,0).text="2025"
        table.cell(1,1).text="15.5"
        stream=io.BytesIO()
        doc.save(stream)
        result=normalize_source(
            stream.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            source_id="word-evidence")
        self.assertEqual(result["blocks"][0]["type"],"heading")
        self.assertEqual(result["tables"][0]["rows"][1],["2025","15.5"])

    def test_pdf_page_numbers_and_scan_warning(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF extra not installed")
        doc = fitz.open()
        doc.new_page().insert_text((80, 80), "Verified source page one")
        doc.new_page()  # Image-only or blank PDF pages need OCR/VLM path.
        data = doc.tobytes()
        doc.close()
        parsed = normalize_source(data, "application/pdf", source_id="pdf-1")
        self.assertEqual(parsed["blocks"][0]["location"]["page"], 1)
        self.assertIn("page_without_extractable_text:2", parsed["warnings"])


if __name__ == "__main__":
    unittest.main()
