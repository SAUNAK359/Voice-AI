"""V26 out-of-core analytics: real CSV/XLSX, SQLite and editable profile QA.

These offline checks validate the implementation, not paid Gemini reliability
or production-scale 200 MB throughput.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_stream_analytics import (
    StreamingSQLDataset, analyze_streaming_sql, summarized_artifact_table,
    render_profile_workbook, verify_profile_workbook)
from rizzler.work_quality import inspect_artifact


def sample_csv(path: Path, size: int = 25000):
    with path.open("w",encoding="utf-8",newline="") as file:
        rows=csv.writer(file)
        rows.writerow(["quarter","imports","exports","region"])
        for index in range(size):
            rows.writerow(["Q"+str(index%4+1),index%7+10,index%7+5,
                           "North" if index%2 else "South"])


class StreamedAnalyticsTests(unittest.TestCase):
    def test_more_than_legacy_rows_and_bound_source_receipt(self):
        with TemporaryDirectory() as temp:
            source=Path(temp)/"real.csv"
            sample_csv(source,30001)
            result=analyze_streaming_sql(source)
            summary=result["summary"]
            self.assertEqual(summary["rows"],30001)
            self.assertEqual(summary["sql_row_count"],30001)
            self.assertEqual(summary["source_coverage"],"full_uploaded_dataset")
            self.assertEqual(summary["numeric_exact"]["imports"]["count"],30001)
            self.assertEqual(summary["source_sha256"],
                             hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(len(summarized_artifact_table(summary)[1]),2)

    def test_read_only_sql_and_private_db_cleanup(self):
        with TemporaryDirectory() as temp:
            source=Path(temp)/"source.csv"
            sample_csv(source,80)
            sandbox=StreamingSQLDataset(source)
            try:
                self.assertEqual(
                    sandbox.query("SELECT COUNT(*) FROM dataset")["rows"],[[80]])
                for statement in ("DELETE FROM dataset",
                                  "SELECT * FROM dataset",
                                  "SELECT sqlite_version()",
                                  "SELECT c0 FROM dataset"):
                    with self.subTest(statement=statement),self.assertRaises(
                        (ValueError,PermissionError,Exception)):
                        sandbox.query(statement)
            finally:
                db=sandbox.db_path
                sandbox.close()
                self.assertFalse(db.exists())

    def test_reject_bad_rows_nonfinite_and_private_symlink(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/"bad.csv"
            path.write_text("x,y\n1,2\n3\n",encoding="utf-8")
            with self.assertRaises(ValueError):analyze_streaming_sql(path)
            path.write_text("x,y\n1,2\nNaN,3\n",encoding="utf-8")
            with self.assertRaises(ValueError):analyze_streaming_sql(path)
            path.write_text("x,y\n1,2\n",encoding="utf-8")
            alias=Path(temp)/"alias.csv"
            try:alias.symlink_to(path)
            except (OSError,NotImplementedError):
                return
            with self.assertRaises(ValueError):analyze_streaming_sql(alias)

    def test_duplicates_missing_and_exact_decimal_sum(self):
        with TemporaryDirectory() as temp:
            source=Path(temp)/"data.csv"
            source.write_text("a,b\n0.1,\n0.1,\n0.2,4\n",encoding="utf-8")
            result=analyze_streaming_sql(source)["summary"]
            self.assertEqual(result["rows"],3)
            self.assertEqual(result["duplicates"],1)
            self.assertEqual(result["missing"]["b"],2)
            self.assertEqual(result["numeric_exact"]["a"]["sum"],"0.4")

    @unittest.skipUnless(importlib.util.find_spec("openpyxl") is not None,
                         "OpenPyXL required for XLSX streaming")
    def test_xlsx_reader_and_formula_fallback(self):
        from openpyxl import Workbook
        with TemporaryDirectory() as temp:
            path=Path(temp)/"real.xlsx"
            workbook=Workbook()
            worksheet=workbook.active
            worksheet.append(["period","sales"])
            for index in range(500):worksheet.append([f"Q{index%4+1}",index+1])
            workbook.save(path);workbook.close()
            result=analyze_streaming_sql(path)
            self.assertEqual(result["summary"]["rows"],500)
            self.assertEqual(result["summary"]["numeric_exact"]["sales"]["sum"],"125250")

    @unittest.skipUnless(importlib.util.find_spec("openpyxl") is not None,
                         "OpenPyXL required for native workbook")
    def test_editable_profile_and_tamper_rejection(self):
        from openpyxl import load_workbook
        with TemporaryDirectory() as temp:
            root=Path(temp)
            source=root/"data.csv"
            sample_csv(source,200)
            summary=analyze_streaming_sql(source)["summary"]
            workbook=root/"profile.xlsx"
            sections=[("Executive takeaway","All 200 observations were processed."),
                      ("Limitations","Source field units are unspecified.")]
            render_profile_workbook(workbook,summary,"Source analysis",sections,[])
            report=verify_profile_workbook(workbook,summary)
            self.assertTrue(report["passed"])
            inspected=inspect_artifact(workbook,"xlsx",dataset_summary=summary)
            self.assertTrue(inspected["passed"])
            self.assertIn("full_source_profile_independently_reconciled",
                          inspected["checks"])
            file=load_workbook(workbook)
            file["Data"]["B2"]=999999
            file.save(workbook);file.close()
            with self.assertRaises(ValueError):
                verify_profile_workbook(workbook,summary)

    def test_private_sql_groups_and_string_aggregation_are_rejected(self):
        with TemporaryDirectory() as temp:
            source=Path(temp)/"data.csv"
            source.write_text(
                "category,value\\nA,1\\nA,2\\nB,3\\nB,4\\nB,5\\n",encoding="utf-8")
            sandbox=StreamingSQLDataset(source)
            try:
                with self.assertRaises((ValueError,__import__("sqlite3").DatabaseError)):
                    sandbox.query(
                        "SELECT c0, COUNT(*) AS group_count FROM dataset GROUP BY c0")
                with self.assertRaises((ValueError,__import__("sqlite3").DatabaseError)):
                    sandbox.query(
                        "SELECT GROUP_CONCAT(c0),COUNT(*) FROM dataset")
                allowed=sandbox.query(
                    "SELECT COUNT(*) AS observations FROM dataset")
                self.assertEqual(allowed["rows"],[[5]])
            finally:
                sandbox.close()

    def test_bounded_number_of_rows_is_fail_closed(self):
        with TemporaryDirectory() as temp:
            source=Path(temp)/"data.csv"
            sample_csv(source,70)
            with patch("rizzler.work_stream_analytics.MAX_ROWS",50):
                with self.assertRaises(ValueError):
                    analyze_streaming_sql(source)


if __name__=="__main__":
    unittest.main()
