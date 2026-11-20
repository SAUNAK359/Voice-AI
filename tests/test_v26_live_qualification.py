"""V26 live release harness and Kaggle notebook structural/safety acceptance.

All checks are offline. Only a future authorized Kaggle/Colab run can prove
actual paid Gemini research, professional artifact utility or visual quality.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
RUNNER=ROOT/"scripts"/"qualify_v26_live.py"
NOTEBOOK=ROOT/"notebooks"/"Rizzler_V26_Real_Gemini_Qualification_Kaggle.ipynb"


class V26LiveQualificationContractTests(unittest.TestCase):
    def test_runner_is_python_valid_and_pins_actual_git_revision(self):
        code=RUNNER.read_text(encoding="utf-8")
        compile(code,str(RUNNER),"exec")
        self.assertIn("expected-sha",code)
        self.assertIn('sha!=options.expected_sha',code)
        self.assertIn("RIZZLER_V26_CONTEXT_FABRIC",code)
        self.assertIn("RIZZLER_V26_OUTCOME_PHASES",code)
        self.assertIn("RIZZLER_V26_EDITORIAL_DIRECTOR",code)
        self.assertIn("RIZZLER_V26_ARTIFACT_STRATEGY",code)
        self.assertIn("RIZZLER_ARTIFACT_QA",code)
        self.assertIn('os.environ.get("GEMINI_API_KEY")',code)
        self.assertIn("from qualify_v25_live import run_paid",code)
        self.assertIn('report["release_status"]="CANDIDATE_SMOKE_TEST_ONLY"',code)
        self.assertIn('report["passed"]=report["offline_passed"]',code)
        self.assertIn('return 0 if report["passed"] else 1',code)

    def test_notebook_python_cells_compilable_and_secret_remains_in_kaggle(self):
        nb=json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        self.assertEqual(nb.get("nbformat"),4)
        self.assertGreaterEqual(len(nb.get("cells",[])),6)
        code=[]
        for i,item in enumerate(nb["cells"]):
            if item["cell_type"]!="code":
                continue
            raw="".join(item["source"])
            compile(raw,f"v26_kaggle_cell_{i}","exec",
                    flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            code.append(raw)
        joined="\n".join(code)
        self.assertIn('get_secret("GEMINI_API_KEY")',joined)
        self.assertIn('"--expected-sha",SOURCE_SHA',joined)
        self.assertIn('str(REPO)+"[work,test]"',joined)
        for required in (
                "libreoffice-writer","libreoffice-impress","libreoffice-calc"):
            self.assertIn(required,joined)
        self.assertIn("qualify_v26_live.py",joined)
        self.assertIn("Rizzler_V26_Qualification_",joined)
        self.assertNotIn("AIza",joined)

    def test_diagnostics_bundle_does_not_export_private_workstore(self):
        code=RUNNER.read_text(encoding="utf-8")
        for marker in ("private_workstore","private_slots",
                       ".sqlite3",".pem",".env",".key"):
            self.assertIn(marker,code)
        self.assertIn('report["release_status"]="CANDIDATE_SMOKE_TEST_ONLY"',code)
        self.assertNotIn('report["release_status"]="PRODUCTION_QUALIFIED"',code)


if __name__=="__main__":
    unittest.main()
