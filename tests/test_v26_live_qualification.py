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
        self.assertIn('report["streamed_paid_passed"]',code)
        self.assertIn('report["offline_passed"] and report["live_passed"] and report["streamed_paid_passed"]',code)
        self.assertIn("from qualify_v26_stream_paid import run_streamed_paid",code)
        self.assertIn("RIZZLER_V26_CROSS_ARTIFACT_QA",code)
        self.assertIn("test_v26_stream_paid_submission.py",code)
        self.assertIn("BLOCKED_BY_PROVIDER_PREFLIGHT",code)
        streamed=(ROOT/"scripts"/"qualify_v26_stream_paid.py").read_text()
        self.assertIn('report["safe_review_events"]',streamed)
        self.assertIn('"recovery_controller","cross_artifact_auditor"',streamed)
        self.assertNotIn('event["payload"].get("prompt")',streamed)
        self.assertIn("paid.get(\"preflight\",{}).get(\"passed\") is True",code)
        for required in ("test_v26_cross_artifact_consistency.py",
                         "test_v26_final_release_gate.py",
                         "test_v26_large_uploads.py",
                         "test_v26_stream_analytics.py"):
            self.assertIn(required,code)
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
        self.assertIn("Rizzler_V26_Audit_",joined)
        self.assertIn("feature/v26-final-integration-gates",joined)
        self.assertNotIn("feature/v24-context-convergence-and-safe-repair",joined)
        self.assertIn("verify_release.py",joined)
        self.assertIn("qualify_v26_large_data.py",joined)
        self.assertIn("evaluate_v26_release.py",joined)
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
