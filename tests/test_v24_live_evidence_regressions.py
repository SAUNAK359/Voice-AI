"""V24 live evidence regressions: partial source facts and strict XLSX Calc QA."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.research_intelligence import focus_claims
from rizzler.work_diagnostics import failure_code
from rizzler.work_formula import (
    SpreadsheetRecalculationUnavailable, verify_workbook,
    _missing_system_calc_component)


class PartialResearchSafety(unittest.IsolatedAsyncioTestCase):
    async def test_valid_partial_evidence_is_preserved_without_claiming_full_answer(self):
        claims=[
            {"id":"validated_a","claim":"The documented API uses grounding to retrieve source information.",
             "source_url":"https://example.org/official","interpretation":False},
            {"id":"validated_b","claim":"Irrelevant provider profile information.",
             "source_url":"https://example.org/other","interpretation":False},
        ]
        response=SimpleNamespace(text=json.dumps({
            "answers_question":False,"selected_ids":["validated_a"],
            "missing_aspects":["Official compatibility details remain unavailable."]}))
        with patch("rizzler.cognitive_provider.generate_with_recovery",
                   new=AsyncMock(return_value=response)):
            relevant,audit=await focus_claims(
                "Compare official Gemini native API feature compatibility",
                claims,client=object(),model="mock")
        self.assertEqual([x["id"] for x in relevant],["validated_a"])
        self.assertEqual(audit["status"],"partial_answer")
        self.assertFalse(audit["answers_question"])
        self.assertTrue(audit["missing_aspects"])

    async def test_complete_source_facts_are_distinguished_from_partial(self):
        claims=[{"id":"direct_quote","claim":"The official feature requirement is documented.",
                 "source_url":"https://example.org/primary",
                 "interpretation":False}]
        response=SimpleNamespace(text=json.dumps({
            "answers_question":True,"selected_ids":["direct_quote"],
            "missing_aspects":[]}))
        with patch("rizzler.cognitive_provider.generate_with_recovery",
                   new=AsyncMock(return_value=response)):
            verified,report=await focus_claims(
                "Investigate official feature restrictions",claims,
                client=object(),model="mock")
        self.assertEqual(len(verified),1)
        self.assertEqual(report["status"],"answers_question")
        self.assertTrue(report["answers_question"])


class CalcStrictRuntimeSafety(unittest.TestCase):
    def test_missing_libreoffice_calc_is_diagnosed_without_disabling_recalculation(self):
        from openpyxl import Workbook
        with TemporaryDirectory() as root:
            path=Path(root)/"synthetic_checked.xlsx"
            wb=Workbook()
            wb.active.title="Summary"
            data=wb.create_sheet("Data")
            data.append(["value"])
            data.append([10])
            checks=wb.create_sheet("Checks")
            checks.append(["Metric","Formula","Expected"])
            checks.append(["Source rows","=ROWS(Data!A2:A2)",1])
            checks.append(["Numeric count","=COUNT(Data!A2:A2)",1])
            wb.save(path)
            wb.close()
            def which(name):
                return "/usr/bin/" + name if name in (
                    "libreoffice","dpkg-query") else None
            with patch("rizzler.work_formula.shutil.which",side_effect=which), \
                 patch("rizzler.work_formula.subprocess.run",
                       side_effect=[SimpleNamespace(returncode=1),
                                    SimpleNamespace(returncode=1,stdout=b"")]):
                with self.assertRaisesRegex(
                        SpreadsheetRecalculationUnavailable,
                        "LibreOffice Calc component is missing"):
                    verify_workbook(path,require_recalculation=True)
            # The same failure is not confused with an invalid arithmetic
            # result, nor treated as a successful workbook.
            self.assertEqual(
                failure_code(SpreadsheetRecalculationUnavailable(
                    "Calc conversion failed")),
                "spreadsheet_recalculation_unavailable")

    def test_package_probe_does_not_infer_missing_calc_on_unknown_host(self):
        with patch("rizzler.work_formula.shutil.which",
                   return_value=None):
            self.assertFalse(_missing_system_calc_component())


if __name__=="__main__":
    unittest.main()
