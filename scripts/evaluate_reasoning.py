#!/usr/bin/env python3
"""Run frozen, externally supplied reasoning evaluations with real Gemini.

Requires JSONL dataset and GEMINI_API_KEY. No benchmark result is fabricated
from mock tests, and failures count against accuracy and success rate.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from rizzler.config import Settings
from rizzler.evaluation import grade, load_cases, prompt_for
from rizzler.providers import GeminiLLM


async def run(args):
    cases, digest = load_cases(args.dataset, args.suite, args.seed, args.limit)
    if args.validate:
        print(json.dumps({"valid": True, "cases": len(cases), "dataset_sha256": digest,
                          "status": "shape_only_not_scored"}))
        return 0
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY required for live scoring")
    if not os.environ.get("RIZZLER_ACCESS_KEY"):
        raise RuntimeError("RIZZLER_ACCESS_KEY required; see APP_QUICKSTART.md")
    llm = GeminiLLM(Settings.from_env())
    output, count_ok, count_correct = [], 0, 0
    try:
        for row in cases:
            answer, outcome, error = "", "ok", None
            try:
                async for token in llm.stream(prompt_for(row, args.suite), []):
                    answer += token
            except Exception as exc:
                outcome, error = "failed", type(exc).__name__
            correct = bool(outcome == "ok" and grade(row, answer, args.suite))
            count_ok += outcome == "ok"
            count_correct += correct
            output.append({"id": row["id"], "outcome": outcome, "correct": correct,
                           "error_type": error})
    finally:
        await llm.close()
    report = {
        "schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
        "suite": args.suite, "dataset_sha256": digest, "seed": args.seed,
        "sample_size": len(cases), "model": llm.settings.gemini_model,
        "correct": count_correct, "successful_requests": count_ok,
        "failed_requests": len(cases)-count_ok,
        "accuracy_including_failures": round(count_correct/len(cases), 6),
        "provider_window": llm.telemetry.summary(),
        "scoring_method": "strict extracted numeric/choice or exact reference matching",
        "caveats": ["Not an independent general-purpose hallucination assessment",
                    "No live benchmark claims without this actual run",
                    "Local arithmetic routing is included, not isolated from Gemini"],
        "cases": output,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Completed {len(cases)} real test requests; accuracy including failures: {report['accuracy_including_failures']}")
    return 0 if count_ok == len(cases) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=("gsm8k", "mmlu_pro", "factual"))
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=0, help="0 means full dataset")
    parser.add_argument("--output", type=Path, default=Path("phase3-evaluation.json"))
    parser.add_argument("--validate", action="store_true", help="Offline schema-only validation")
    args = parser.parse_args()
    if args.limit < 0 or args.limit > 100000:
        parser.error("limit must be between 0 and 100000")
    try:
        return asyncio.run(run(args))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Evaluation stopped: {type(exc).__name__}. No performance claim was produced.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
