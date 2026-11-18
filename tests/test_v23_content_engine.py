"""Deterministic content-engine tests: no paid Gemini calls required."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rizzler.content_engine import develop_content, _valid_plan


class ContentEngineTests(unittest.TestCase):
    def test_parallel_drafting_retains_independent_sections(self):
        seen = []
        active = [0]
        max_active = [0]
        plan = {"sections": [
            {"heading": "Methods and limitations", "question": "How are the values measured?",
             "coverage": "Period, methodology, units and uncertainties", "target_words": 150},
            {"heading": "Quantitative findings", "question": "What changed in the dataset?",
             "coverage": "Independent numerical findings and validation", "target_words": 150},
            {"heading": "Competing explanations", "question": "What could explain the change?",
             "coverage": "Causal uncertainties and conflicting interpretations",
             "target_words": 150},
        ]}
        async def generate(prompt, tokens):
            if "Return only JSON" in prompt:
                return json.dumps(plan)
            active[0] += 1
            max_active[0] = max(max_active[0], active[0])
            await asyncio.sleep(0.005)
            active[0] -= 1
            title = next(x["heading"] for x in plan["sections"] if x["heading"] in prompt)
            seen.append(title)
            return ("This section explains real observations, appropriate limits "
                    "and a detailed verification strategy rather than inventing "
                    "unmeasured claims or unreliable statistics. " * 9)
        result = asyncio.run(develop_content(
            "Analyze a user-provided sample and explain meaningful limitations",
            {"rows": 3, "numeric": {"amount": {"mean": 12}}},
            generate, parallelism=3))
        self.assertEqual(result["section_count"], 3)
        self.assertEqual(max_active[0], 3)
        self.assertEqual(len(seen), 3)
        self.assertLess(result["text"].index("## Methods and limitations"),
                        result["text"].index("## Quantitative findings"))
        self.assertLess(result["text"].index("## Quantitative findings"),
                        result["text"].index("## Competing explanations"))

    def test_independent_review_repairs_only_weak_section(self):
        plan = {"sections": [
            {"heading": "Evidence and methodology", "question": "Which data is established?",
             "coverage": "Source limitations and unit reconciliation", "target_words": 150},
            {"heading": "Quantitative interpretation", "question": "How do values relate?",
             "coverage": "Calculations and trends", "target_words": 150},
            {"heading": "Decision implications", "question": "What can be concluded?",
             "coverage": "Bounded implications and alternatives", "target_words": 150},
        ]}
        scores = [0]
        repairs = [0]
        async def generate(prompt, tokens):
            if "Return only JSON" in prompt:
                return json.dumps(plan)
            if "independent expert content auditor" in prompt:
                scores[0] += 1
                return json.dumps({"sections": [{
                    "heading": item["heading"],
                    "passed": scores[0] > 1 or idx != 1,
                    "defects": [] if scores[0] > 1 or idx != 1 else ["Missing comparison"],
                    "repair_guidance": "Add source-bound cross-period comparison"
                    if idx == 1 else ""}
                    for idx, item in enumerate(plan["sections"])]})
            if "Independent review found this specific defect" in prompt:
                repairs[0] += 1
            return ("A complete, source-aware expert section explains methods, "
                    "alternative explanations, uncertainty, measurements and "
                    "what is unknown without invented figures or claims. " * 11)
        result = asyncio.run(develop_content(
            "Investigate evidence and decision implications", None, generate,
            max_characters=18000, review=True))
        self.assertEqual(result["review_rounds"], 2)
        self.assertEqual(repairs[0], 1)

    def test_invalid_or_placeholder_sections_fail_closed(self):
        with self.assertRaises(ValueError):
            _valid_plan({"sections": []})
        async def bad(prompt, tokens):
            if "Return only JSON" in prompt:
                return json.dumps({"sections": [
                    {"heading": f"Section {i} with useful domain specificity",
                     "question": "Explain what methods should be considered",
                     "coverage": "Methods and limitations requiring evidence",
                     "target_words": 200} for i in range(3)]})
            return "Short filler."
        with self.assertRaises(ValueError):
            asyncio.run(develop_content("Create an in-depth technical report", None, bad))

    def test_section_plan_does_not_accept_unauthorized_fields(self):
        item = {"heading": "Meaningful analytical heading",
                "question": "Which assumptions could undermine the result",
                "coverage": "Data validity, limitations, and causality",
                "target_words": 240, "shell_command": "echo unsafe"}
        with self.assertRaises(ValueError):
            _valid_plan({"sections": [item] * 3})


if __name__ == "__main__":
    unittest.main()
