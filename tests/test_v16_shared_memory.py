"""Encrypted Live/Work shared-context isolation contracts."""
from __future__ import annotations
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rizzler.work_shared_memory import relevant_to_work


@unittest.skipUnless(importlib.util.find_spec("cryptography") is not None,
                     "Optional encrypted memory dependency absent")
class SharedMemoryContracts(unittest.TestCase):
    def test_disabled_never_creates_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {
                "RIZZLER_MEMORY_ENABLED": "0",
                "RIZZLER_MEMORY_ROOT": folder}):
                self.assertEqual(relevant_to_work("owner_001", "Weekly business report"), [])
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_owner_isolation_and_optin_recall(self):
        from rizzler.memory import MemoryStore
        with tempfile.TemporaryDirectory() as folder:
            key = "unit-test-secret-" + "x" * 40
            mem = MemoryStore(folder, key)
            mem.remember("owner_001", "Use Indian rupees for business finance reports.")
            env = {
                "RIZZLER_MEMORY_ENABLED": "1",
                "RIZZLER_MEMORY_ROOT": folder,
                "RIZZLER_MEMORY_KEY": key,
            }
            with patch.dict(os.environ, env):
                self.assertEqual(relevant_to_work(
                    "owner_001", "Make a business finance report"),
                    ["Use Indian rupees for business finance reports."])
                self.assertEqual(relevant_to_work(
                    "owner_002", "Make a business finance report"), [])

    def test_invalid_memory_configuration_refuses_insecure_fallback(self):
        with patch.dict(os.environ, {
                "RIZZLER_MEMORY_ENABLED": "1",
                "RIZZLER_MEMORY_KEY": "",
                "RIZZLER_MEMORY_ROOT": ""}, clear=True):
            with self.assertRaises(RuntimeError):
                relevant_to_work("owner_001", "Report")
