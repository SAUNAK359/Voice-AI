"""Coherent full-cognitive feature profile and explicit override tests."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rizzler.v23_flags import enabled,FEATURES


class V23FeatureProfileTests(unittest.TestCase):
    def test_default_is_full_and_explicit_off_remains_possible(self):
        with patch.dict("os.environ",{},clear=True):
            self.assertTrue(all(enabled(key) for key in FEATURES))
        with patch.dict("os.environ",{"RIZZLER_V23_MODE":"off"},clear=True):
            self.assertFalse(any(enabled(key) for key in FEATURES))
        with patch.dict("os.environ",{"RIZZLER_V23_MODE":"full"},clear=True):
            self.assertTrue(all(enabled(key) for key in FEATURES))
        with patch.dict("os.environ",{"RIZZLER_V23_MODE":"full",
                 "RIZZLER_EXCEL_STUDIO":"0"},clear=True):
            self.assertFalse(enabled("RIZZLER_EXCEL_STUDIO"))
            self.assertTrue(enabled("RIZZLER_COGNITIVE_PLANNER"))

    def test_unsafe_or_unknown_config_fails_closed(self):
        with patch.dict("os.environ",{"RIZZLER_V23_MODE":"unsafe"},clear=True):
            with self.assertRaises(ValueError):
                enabled("RIZZLER_COGNITIVE_CONTENT")
        with patch.dict("os.environ",{"RIZZLER_COGNITIVE_CONTENT":"maybe"},clear=True):
            with self.assertRaises(ValueError):
                enabled("RIZZLER_COGNITIVE_CONTENT")
        with patch.dict("os.environ",{},clear=True):
            with self.assertRaises(ValueError):
                enabled("RIZZLER_UNAUTHORIZED_TOOL")


if __name__=="__main__":
    unittest.main()
