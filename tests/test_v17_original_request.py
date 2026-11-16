"""Persist original Live wording without changing the model's executable objective."""
import os
import tempfile
import unittest
from unittest.mock import patch
from rizzler.work_store import WorkStore

class OriginalRequestTests(unittest.TestCase):
    def test_original_user_instruction_is_preserved_separately(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{
                "RIZZLER_AGENTIC_ENABLED":"1"}):
            s=WorkStore(root)
            job=s.submit("owner_001","Create a stakeholder deck",["pptx"],
                         "request_original_00001",[],
                         original_request="Rizzler, show last week's opening and closing prices in a PPT.")
            spec=s.specification("owner_001",job["id"])
            self.assertEqual(spec["objective"],"Create a stakeholder deck")
            self.assertIn("last week's opening",spec["original_request"])
            again=s.submit("owner_001","Create a stakeholder deck",["pptx"],
                          "request_original_00001",[],
                          original_request="Rizzler, show last week's opening and closing prices in a PPT.")
            self.assertEqual(job["id"],again["id"])

    def test_conflicting_replay_is_rejected(self):
        from rizzler.work_store import Conflict
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{
                "RIZZLER_AGENTIC_ENABLED":"1"}):
            s=WorkStore(root)
            s.submit("owner_001","Make a report",["pdf"],"dedupe_00001",[],
                     original_request="Create a PDF")
            with self.assertRaises(Conflict):
                s.submit("owner_001","Make a report",["pdf"],"dedupe_00001",[],
                         original_request="Create a different PDF")
