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
        self.assertIn("RIZZLER_V24_QUALIFY_SHA",body)
        self.assertNotIn("622a3282878ff29e19f43a360cd807a602951905",body)
        self.assertNotIn("asyncio.run(",body)
        self.assertIn('RIZZLER_V23_MODE"]="full"',body)
        self.assertIn("WorkWorker(store).once()",body)
        self.assertIn("research_status",body)
        self.assertIn("sha256",body)
        self.assertIn("NOT_QUALIFIED",body)
        self.assertNotIn("sk-",body)

    def test_both_live_notebooks_avoid_nested_event_loops_and_compile(self):
        for filename in (
            "Rizzler_V24_Live_Qualification_Kaggle.ipynb",
            "Rizzler_V24_Real_Gemini_Qualification_Kaggle.ipynb"
        ):
            with self.subTest(filename=filename):
                obj=json.loads((ROOT/"notebooks"/filename).read_text(encoding="utf-8"))
                text="\\n".join("".join(cell["source"]) for cell in obj["cells"])
                if cell["cell_type"]=="code")
                self.assertIn("await WorkWorker(store).once()",text)
                self.assertNotIn("asyncio.run(",text)
                self.assertIn("diagnostics",text)
                self.assertIn(".zip",text)
                for i,cell in enumerate(obj["cells"]):
                    if cell["cell_type"]=="code":
                        compile("".join(cell["source"]),f"{filename}:{i}","exec",
                                flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)


if __name__=="__main__":
    unittest.main()
