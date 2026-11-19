"""Static qualification notebook checks; never execute live API cells in CI."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
NOTEBOOK=ROOT/"notebooks"/"Rizzler_V24_Live_Qualification_Kaggle.ipynb"


class V24LiveQualificationNotebookTests(unittest.TestCase):
    def test_notebook_is_valid_json_python_with_no_recorded_outputs(self):
        doc=json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        self.assertEqual(doc["nbformat"],4)
        code_cells=0
        for index,cell in enumerate(doc["cells"]):
            self.assertIn(cell["cell_type"],("code","markdown"))
            content="".join(cell["source"])
            if cell["cell_type"]=="code":
                code_cells+=1
                ast.parse(content,filename=f"V24_qualification_cell_{index}.py")
                self.assertEqual(cell["outputs"],[])
                self.assertIsNone(cell["execution_count"])
        self.assertGreaterEqual(code_cells,8)

    def test_live_qualification_pins_source_and_requires_real_evidence(self):
        doc=json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        body="\n".join("".join(x["source"]) for x in doc["cells"])
        self.assertIn("GEMINI_API_KEY",body)
        self.assertIn("622a3282878ff29e19f43a360cd807a602951905",body)
        self.assertIn('RIZZLER_V23_MODE"]="full"',body)
        self.assertIn("WorkWorker(store).once()",body)
        self.assertIn("research_status",body)
        self.assertIn("sha256",body)
        self.assertIn("NOT_QUALIFIED",body)
        self.assertNotIn("sk-",body)

if __name__=="__main__":
    unittest.main()
