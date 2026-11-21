"""Reproduce the real Kaggle 15,017-row fixture admission without Gemini.

Only the source fixture/WorkStore submission is qualified here. No mock model
output may be mistaken for a live Work success.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"scripts"))
from qualify_v26_stream_paid import KINDS, fixture
from rizzler.work_store import WorkStore
from rizzler.work_stream_analytics import analyze_streaming_sql


class V26StreamPaidSubmissionTests(unittest.TestCase):
    def test_exact_live_fixture_upload_plan_and_source_reconciliation(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ,{
                "RIZZLER_V26_STREAM_ANALYTICS":"1"}):
            root=Path(tmp)
            path,expected=fixture(root/"private_workstore"/"live_fixture")
            store=WorkStore(root/"private_workstore")
            content=path.read_bytes()
            self.assertLess(len(content),8_000_000)
            uploaded=store.register_upload("v26_stream_owner",path.name,content)
            objective=(
                "Produce an executive, source-grounded comparative report for "
                "the uploaded SYNTHETIC 15,017-row import/export dataset. Use "
                "the actual full-source totals, explicitly state the source "
                "is fictional, analyze concentration and numerical limitations "
                "without inventing statistical significance. Deliver native "
                "Excel profile, PowerPoint, Word, PDF and ZIP, all traceable.")
            job=store.submit("v26_stream_owner",objective,sorted(KINDS),
                "v26_stream_fixture_00001",[uploaded["id"]],
                requested_formats=sorted(KINDS))
            self.assertEqual(job["status"],"queued")
            self.assertEqual({row["agent"] for row in
                              store.agent_steps("v26_stream_owner",job["id"])},
                             {"sql_analytics","orchestrator","powerpoint",
                              "word","excel","pdf_visual","quality"})
            observed=analyze_streaming_sql(
                store.upload("v26_stream_owner",uploaded["id"]))["summary"]
            self.assertEqual(observed["rows"],expected["rows"])
            self.assertEqual(observed["source_sha256"],expected["sha256"])
            self.assertEqual(int(observed["numeric_exact"]["imports"]["sum"]),
                             expected["imports"])
            self.assertEqual(int(observed["numeric_exact"]["exports"]["sum"]),
                             expected["exports"])


if __name__=="__main__":
    unittest.main()
