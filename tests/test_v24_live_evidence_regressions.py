"""V24 source-preserving research and strict external Calc regression contracts.

Pure, provider-free tests run even in minimal CI. Real Gemini, openpyxl and
LibreOffice integrations are covered by the separate live qualification job.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rizzler.research_intelligence import project_focus_decision
from rizzler.work_diagnostics import failure_code
from rizzler.work_formula import (
    SpreadsheetRecalculationUnavailable, _convert_calc_for_recalculation,
    _missing_system_calc_component)


class PartialResearchSafety(unittest.TestCase):
    def test_valid_partial_evidence_is_preserved_without_claiming_full_answer(self):
        claims = [
            {"id":"validated_a", "claim":"The officially documented API has grounded search.",
             "source_url":"https://example.org/primary","interpretation":False},
            {"id":"validated_b","claim":"Other provider biography.",
             "source_url":"https://example.org/other","interpretation":False},
        ]
        verdict = {"answers_question":False,"selected_ids":["validated_a"],
                   "missing_aspects":["Official compatibility details remain unavailable."]}
        relevant, audit = project_focus_decision(verdict, claims)
        self.assertEqual([item["id"] for item in relevant], ["validated_a"])
        self.assertEqual(audit["status"], "partial_answer")
        self.assertFalse(audit["answers_question"])
        self.assertEqual(audit["selected"], 1)
        self.assertTrue(audit["missing_aspects"])

    def test_research_completion_requires_positive_full_coverage_verdict(self):
        claims = [{"id":"direct_quote","claim":"The primary documentation states the feature requirement.",
                   "source_url":"https://example.org/primary",
                   "interpretation":False}]
        verdict = {"answers_question":True,"selected_ids":["direct_quote"],
                   "missing_aspects":[]}
        accepted, report = project_focus_decision(verdict, claims)
        self.assertEqual(len(accepted),1)
        self.assertEqual(report["status"],"answers_question")
        self.assertTrue(report["answers_question"])

    def test_empty_or_invented_source_ids_never_become_approved_evidence(self):
        claims = [{"id":"a","claim":"Source-backed fact"}]
        empty, status = project_focus_decision(
            {"answers_question":False,"selected_ids":[],
             "missing_aspects":["Official facts still needed"]},claims)
        self.assertEqual(empty, [])
        self.assertEqual(status["status"],"unanswered_objective")
        with self.assertRaises(ValueError):
            project_focus_decision(
                {"answers_question":True,"selected_ids":["fabricated"],
                 "missing_aspects":[]},claims)


class CalcStrictRuntimeSafety(unittest.TestCase):
    def test_missing_calc_does_not_become_success_or_fake_formula_result(self):
        with TemporaryDirectory() as root:
            source = Path(root) / "dataset.xlsx"
            output = Path(root) / "out"
            output.mkdir()
            source.write_bytes(b"test input: conversion intentionally mocked")
            def which(name):
                return "/usr/bin/" + name if name == "dpkg-query" else None
            with patch("rizzler.work_formula.shutil.which", side_effect=which), \
                 patch("rizzler.work_formula.subprocess.run",
                       side_effect=[SimpleNamespace(returncode=1),
                                    SimpleNamespace(returncode=1,stdout=b"")]):
                with self.assertRaisesRegex(
                        SpreadsheetRecalculationUnavailable,
                        "LibreOffice Calc component is missing"):
                    _convert_calc_for_recalculation(
                        "/usr/bin/libreoffice",source,output,"file:///tmp/prof")
            self.assertEqual(
                failure_code(SpreadsheetRecalculationUnavailable(
                    "LibreOffice conversion failed")),
                "spreadsheet_recalculation_unavailable")

    def test_converter_zero_exit_without_real_xlsx_still_fails(self):
        with TemporaryDirectory() as root:
            source = Path(root) / "source.xlsx"
            output = Path(root) / "out"
            output.mkdir()
            with patch("rizzler.work_formula.shutil.which",
                       return_value=None), patch(
                       "rizzler.work_formula.subprocess.run",
                       return_value=SimpleNamespace(returncode=0)):
                with self.assertRaises(SpreadsheetRecalculationUnavailable):
                    _convert_calc_for_recalculation(
                        "libreoffice",source,output,"file:///tmp/prof")

    def test_unknown_host_does_not_assume_calc_missing(self):
        with patch("rizzler.work_formula.shutil.which",return_value=None):
            self.assertFalse(_missing_system_calc_component())


if __name__ == "__main__":
    unittest.main()
