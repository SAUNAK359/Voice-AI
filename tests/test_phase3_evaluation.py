"""Reproducible benchmark evaluation contracts (fixtures only, not benchmark scores)."""
from __future__ import annotations
import importlib.util
import unittest
if importlib.util.find_spec("pytest") is None:
    raise unittest.SkipTest("App test dependencies unavailable")
import json
import pytest
from rizzler.evaluation import extract_number, extract_choice, grade, load_cases, prompt_for


def test_gsm8k_exact_scoring_and_no_numeric_guess_when_absent():
    assert extract_number("work shown\n#### 1,234.50") == "1234.5"
    assert extract_number("The answer is -10.") == "-10"
    assert extract_number("No known answer") is None
    assert grade({"answer": "#### 72"}, "72", "gsm8k")
    assert not grade({"answer": "#### 72"}, "I cannot verify this", "gsm8k")


def test_mmlu_pro_choice_and_balanced_subject_sampling(tmp_path):
    path = tmp_path / "mmlu.jsonl"
    data = [{"id": f"a{i}", "question": f"Question A {i}", "options": ["x", "y"],
             "answer": "A", "category": "alpha"} for i in range(4)] + [
            {"id": f"b{i}", "question": f"Question B {i}", "options": ["x", "y"],
             "answer": "B", "category": "beta"} for i in range(4)]
    path.write_text("\n".join(json.dumps(row) for row in data), encoding="utf-8")
    cases, digest = load_cases(path, "mmlu_pro", seed=42, limit=4)
    repeat, repeat_digest = load_cases(path, "mmlu_pro", seed=42, limit=4)
    assert cases == repeat and digest == repeat_digest
    assert [x["category"] for x in cases] == ["alpha", "beta", "alpha", "beta"]
    assert extract_choice("Answer: B") == "B"
    assert grade(data[0], "A", "mmlu_pro")
    assert not grade(data[0], "C", "mmlu_pro")
    assert "A. x" in prompt_for(data[0], "mmlu_pro")


def test_schema_validation_refuses_bad_inputs(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps({"question": "Valid sample question", "options": ["x"],
                                "answer": "A"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(path, "mmlu_pro", seed=1, limit=0)
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(path, "gsm8k", seed=1, limit=0)


def test_factual_exact_match_is_not_general_hallucination_judge():
    case = {"question": "Capital of France?", "answer": "Paris", "aliases": ["Paris, France"]}
    assert grade(case, "PARIS", "factual")
    assert not grade(case, "Paris probably", "factual")
