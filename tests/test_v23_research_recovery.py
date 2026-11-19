"""Goal-missing source recovery must remain bounded and provenance scoped."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.research_recovery import bounded_gaps, recover_missing_research


class GapRecoveryPolicyTests(unittest.TestCase):
    def test_specific_obligations_are_deduplicated_and_bounded(self):
        data=["  Missing actual trade figures for FY2024-25.  ",
              "Missing actual trade figures for FY2024-25.",
              "No original customs statistics for comparison.",
              "Unspecified methodology behind unit conversion."]
        gaps=bounded_gaps(data)
        self.assertEqual(len(gaps),2)
        self.assertEqual(gaps[0],"Missing actual trade figures for FY2024-25.")
        self.assertEqual(gaps[1],"No original customs statistics for comparison.")

    def test_invalid_or_empty_input_cannot_trigger_search(self):
        self.assertEqual(bounded_gaps("web search everything"),())
        self.assertEqual(bounded_gaps(["", "short", 72, "\x01malicious"]),())
        self.assertEqual(bounded_gaps(["Missing original statistics"],limit=0),())

    def test_no_missing_obligations_makes_no_provider_call(self):
        result=asyncio.run(recover_missing_research(
            "Investigate the recorded merchandise trade result",[],
            client=None,model="unused",previously_seen=set()))
        self.assertEqual(result["status"],"no_specific_missing_requirements")
        self.assertEqual(result["attempts"],0)
        self.assertEqual(result["claims"],[])


if __name__=="__main__":
    unittest.main()
