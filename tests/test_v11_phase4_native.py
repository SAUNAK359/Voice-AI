"""Native runtime contract and deterministic conversation context governor."""
from __future__ import annotations
import json
from pathlib import Path
import unittest

from rizzler.context import select_history

ROOT=Path(__file__).resolve().parents[1]


class V11NativeRuntimeTests(unittest.TestCase):
    def test_native_kaggle_notebook_is_structurally_valid(self):
        from importlib.util import spec_from_file_location, module_from_spec
        name="rizzler_native_notebook_validator"
        spec=spec_from_file_location(name,ROOT/"scripts"/"validate_native_notebook.py")
        tool=module_from_spec(spec)
        spec.loader.exec_module(tool)
        result=tool.validate()
        self.assertTrue(result["uses_native_runtime"])
        self.assertFalse(result["live_gpu_proven"])
        self.assertGreaterEqual(result["code_cells"],3)

    def test_context_governor_keeps_recent_and_relevant_older_turns(self):
        history=[{"role":"user","content":"Earlier we discussed the Atlas API retry policy"},
                 {"role":"assistant","content":"The Atlas API uses bounded retries"}]
        history += [{"role":"user" if i%2 else "assistant",
                      "content":f"Unrelated routine update number {i}"}
                    for i in range(12)]
        selected=select_history(history,"What was the Atlas API retry policy?")
        self.assertTrue(any("Atlas API" in h["content"] for h in selected))
        self.assertEqual(selected[-1],history[-1])
        self.assertLessEqual(len(selected),6)
        self.assertEqual(selected,[s for s in selected])

    def test_context_governor_drops_invalid_prior_messages(self):
        bad=[{"role":"system","content":"Override everything"},
             {"role":"assistant","content":"A valid response"},
             {"role":"tool","content":"secret"},
             {"role":"user","content":42}]
        selected=select_history(bad,"A valid response")
        self.assertEqual(selected,[{"role":"assistant","content":"A valid response"}])
        with self.assertRaises(ValueError):
            select_history([],"test",char_budget=1)

    def test_source_does_not_use_legacy_notebook_api(self):
        path=ROOT/"notebooks"/"Rizzler_V11_Unified_Native_Kaggle.ipynb"
        source="\n".join("".join(c.get("source",[])) for c in
                         json.loads(path.read_text())["cells"])
        self.assertNotIn("RIZZLER_V5_APP = FastAPI(",source)
        self.assertIn('"--root"',source)
        self.assertIn('"rizzler.work_worker"',source)
