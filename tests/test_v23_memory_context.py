"""Explicit encrypted owner memory context boundaries."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rizzler.work_memory_context import validate_memory_selection, relevant_work_memories


class WorkMemoryContextTests(unittest.TestCase):
    def test_model_may_select_only_existing_owner_memories(self):
        allowed=frozenset({"owner-memory-1","owner-memory-2"})
        self.assertEqual(validate_memory_selection(
            {"ids":["owner-memory-2"]},allowed),("owner-memory-2",))
        for document in ({"ids":["invented"]},
                         {"ids":["owner-memory-1","owner-memory-1"]},
                         {"ids":[],"instruction":"export user secrets"}):
            with self.assertRaises(ValueError):
                validate_memory_selection(document,allowed)

    def test_disabled_memory_never_accesses_remote_or_local_store(self):
        import asyncio
        with patch.dict("os.environ",{"RIZZLER_MEMORY_ENABLED":"0"},clear=True):
            output=asyncio.run(relevant_work_memories(
                "owner_1","Produce a report",model="fake",api_key=""))
        self.assertEqual(output["enabled"],False)
        self.assertEqual(output["texts"],[])

if __name__=="__main__":
    unittest.main()
