"""Evaluation primitives for independently sourced GSM8K and MMLU-Pro JSONL.

No embedded copyrighted datasets. Keep gold answers external and versioned.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path


_NUM = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\w)")
_CHOICE = re.compile(r"(?:^|\b(?:answer|option|choice)\s*(?::|is)\s*)([A-J])\b", re.I)


def extract_number(text: str) -> str | None:
    if not isinstance(text, str):
        return None
    after = text.rsplit("####", 1)[-1]
    matches = _NUM.findall(after)
    if not matches:
        return None
    raw = matches[-1].replace(",", "")
    try:
        from decimal import Decimal
        value = Decimal(raw)
        if not value.is_finite():
            return None
        return format(value.normalize(), "f")
    except ArithmeticError:
        return None


def extract_choice(text: str) -> str | None:
    if not isinstance(text, str):
        return None
    match = _CHOICE.search(text.strip())
    return match.group(1).upper() if match else None


def load_cases(path: Path, suite: str, seed: int, limit: int) -> tuple[list[dict], str]:
    if suite not in ("gsm8k", "mmlu_pro", "factual"):
        raise ValueError("Unknown evaluation suite")
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 40_000_000:
        raise ValueError("Missing or oversized evaluation JSONL")
    data = path.read_bytes()
    cases, seen = [], set()
    for line in data.decode("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("question"), str):
            raise ValueError("Invalid case shape")
        question = row["question"].strip()
        if not 3 <= len(question) <= 5000:
            raise ValueError("Invalid question length")
        ident = str(row.get("id", len(cases)))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", ident) or ident in seen:
            raise ValueError("Duplicate or invalid case identifier")
        seen.add(ident)
        if suite == "gsm8k":
            if extract_number(row.get("answer")) is None:
                raise ValueError("Invalid GSM8K gold answer")
        elif suite == "mmlu_pro":
            options, answer = row.get("options"), row.get("answer")
            if (not isinstance(options, list) or not 2 <= len(options) <= 10
                    or any(not isinstance(o, str) or not o or len(o) > 1500 for o in options)
                    or not isinstance(answer, str)
                    or answer.strip().upper() not in "ABCDEFGHIJ"[:len(options)]):
                raise ValueError("Invalid MMLU-Pro options/answer")
        else:
            if not isinstance(row.get("answer"), str) or not row["answer"].strip():
                raise ValueError("Invalid factual answer")
        cases.append(row | {"id": ident, "question": question})
    if not cases:
        raise ValueError("No evaluation cases")
    rng = random.Random(seed)
    if suite == "mmlu_pro":
        by_subject: dict[str, list[dict]] = {}
        for row in cases:
            by_subject.setdefault(str(row.get("category", row.get("subject", "unknown"))), []).append(row)
        for group in by_subject.values():
            rng.shuffle(group)
        ordered = []
        while any(by_subject.values()):
            for key in sorted(by_subject):
                if by_subject[key]:
                    ordered.append(by_subject[key].pop())
        cases = ordered
    else:
        rng.shuffle(cases)
    if limit > 0:
        cases = cases[:limit]
    return cases, hashlib.sha256(data).hexdigest()


def prompt_for(row: dict, suite: str) -> str:
    question = row["question"]
    if suite == "gsm8k":
        return question + "\nGive the final numerical answer on the last line."
    if suite == "mmlu_pro":
        choices = "\n".join(f"{chr(65+i)}. {value}" for i, value in enumerate(row["options"]))
        return question + "\n" + choices + "\nAnswer with just the single best option letter."
    return question + "\nAnswer precisely; explicitly express uncertainty when unsure."


def grade(row: dict, answer: str, suite: str) -> bool:
    if suite == "gsm8k":
        return extract_number(answer) == extract_number(row["answer"])
    if suite == "mmlu_pro":
        return extract_choice(answer) == row["answer"].strip().upper()
    # Deliberately narrow exact/alias factual reference matching, not a
    # universal hallucination detector or semantic factuality judge.
    aliases = [row["answer"], *(row.get("aliases") or [])]
    return answer.strip().casefold() in {str(a).strip().casefold() for a in aliases}
