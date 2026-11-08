#!/usr/bin/env python3
"""WER/CER scorer on reference,hypothesis CSV. No transcript contents in output."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import re
import unicodedata


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, a in enumerate(reference, 1):
        current = [i]
        for j, b in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[j-1] + 1, previous[j-1] + (a != b)))
        previous = current
    return previous[-1]


def score(rows: list[dict], dataset: str) -> dict:
    if not rows:
        raise ValueError("No ASR data")
    word_edits = char_edits = word_count = char_count = 0
    missing = 0
    for row in rows:
        if "reference" not in row or "hypothesis" not in row:
            raise ValueError("Expected reference and hypothesis columns")
        ref, hyp = normalize(row["reference"]), normalize(row["hypothesis"])
        if not ref:
            missing += 1
            continue
        wr, wh = ref.split(), hyp.split()
        word_edits += distance(wr, wh)
        char_edits += distance(list(ref.replace(" ", "")), list(hyp.replace(" ", "")))
        word_count += len(wr)
        char_count += len(ref.replace(" ", ""))
    if not word_count or not char_count:
        raise ValueError("No non-empty reference transcripts")
    return {"dataset_id": dataset, "status": "evaluated_inputs_not_verified_dataset_origin",
            "utterances_total": len(rows), "utterances_scored": len(rows)-missing,
            "references_missing": missing,
            "wer": round(word_edits/word_count, 5), "cer": round(char_edits/char_count, 5),
            "reference_words": word_count, "reference_characters": char_count,
            "word_edit_distance": word_edits, "character_edit_distance": char_edits,
            "normalization": "Unicode NFKC, casefold, punctuation to spaces, whitespace collapse"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    with args.input.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    result = score(rows, args.dataset_id)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
