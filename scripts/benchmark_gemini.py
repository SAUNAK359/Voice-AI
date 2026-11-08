#!/usr/bin/env python3
"""Measure Gemini REST SSE TTFT without logging prompts, responses or credentials.

Run from Kaggle/your own machine with GEMINI_API_KEY in secrets/environment.
The --dry-run path is offline and produces no performance claims.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
from urllib import request, error
from urllib.parse import quote
import uuid

MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,99}$")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/"
DEFAULT_PROMPTS = Path(__file__).resolve().parents[1] / "benchmarks" / "fixtures" / "gemini_prompts.jsonl"


def get_secret():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    try:
        from kaggle_secrets import UserSecretsClient
        return (UserSecretsClient().get_secret("GEMINI_API_KEY") or "").strip()
    except (ImportError, KeyError, RuntimeError, ValueError):
        return ""


def load_prompts(path: Path) -> list[dict]:
    prompts = []
    ids = set()
    for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        record = json.loads(raw)
        ident, prompt = record.get("id"), record.get("prompt")
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", ident):
            raise ValueError(f"Invalid prompt id at line {index}")
        if ident in ids or not isinstance(prompt, str) or not 3 <= len(prompt) <= 2000:
            raise ValueError(f"Duplicate id or invalid prompt at line {index}")
        ids.add(ident)
        prompts.append({"id": ident, "prompt": prompt})
    if not prompts or len(prompts) > 100:
        raise ValueError("Expected between 1 and 100 bounded prompts")
    return prompts


def extract_visible_text(event: dict) -> str:
    """A Gemini SSE event may contain thoughts, metadata or empty chunks."""
    parts = []
    for candidate in event.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            if part.get("thought") is True:
                continue
            if isinstance(part.get("text"), str) and part["text"].strip():
                parts.append(part["text"])
    return "".join(parts)


def stream_gemini(prompt: str, model: str, api_key: str, timeout: int = 90, opener=None) -> dict:
    """Return only safe metrics. One uncached request, no retries, no response text."""
    if not MODEL_PATTERN.fullmatch(model):
        raise ValueError("Invalid Gemini model identifier")
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY")
    url = f"{BASE_URL}{quote(model)}:streamGenerateContent?alt=sse"
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 256, "temperature": 0},
    }).encode("utf-8")
    req = request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "x-goog-api-key": api_key,
    })
    opener = opener or request.urlopen
    started = time.perf_counter()
    first_text_ms = None
    first_event_ms = None
    output_chars = 0
    chunk_count = 0
    usage_tokens = None
    try:
        with opener(req, timeout=timeout) as response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if first_event_ms is None:
                    first_event_ms = round((time.perf_counter() - started) * 1000, 2)
                delta = extract_visible_text(event)
                if delta:
                    if first_text_ms is None:
                        first_text_ms = round((time.perf_counter() - started) * 1000, 2)
                    chunk_count += 1
                    output_chars += len(delta)
                usage = event.get("usageMetadata") or {}
                if isinstance(usage.get("candidatesTokenCount"), int):
                    usage_tokens = usage["candidatesTokenCount"]
    except error.HTTPError as exc:
        return {"outcome": "error", "error_code": f"http_{exc.code}",
                "total_ms": round((time.perf_counter() - started) * 1000, 2),
                "ttft_ms": None, "first_event_ms": first_event_ms}
    except (error.URLError, TimeoutError, OSError, UnicodeError) as exc:
        return {"outcome": "error", "error_code": type(exc).__name__,
                "total_ms": round((time.perf_counter() - started) * 1000, 2),
                "ttft_ms": None, "first_event_ms": first_event_ms}
    total_ms = round((time.perf_counter() - started) * 1000, 2)
    return {"outcome": "ok" if first_text_ms is not None else "error",
            "error_code": None if first_text_ms is not None else "no_visible_text",
            "ttft_ms": first_text_ms, "first_event_ms": first_event_ms,
            "total_ms": total_ms, "output_chars": output_chars,
            "text_chunks": chunk_count, "output_tokens": usage_tokens}


def percentile(data: list[float], p: float) -> float | None:
    if not data:
        return None
    data = sorted(data)
    from math import ceil
    return round(data[max(0, ceil(p / 100 * len(data)) - 1)], 2)


def summarize(records: list[dict], target_ms: float = 564) -> dict:
    # Errors and warmups do NOT contribute to successful TTFT latency.
    measured = [float(r["ttft_ms"]) for r in records
                if r.get("outcome") == "ok" and isinstance(r.get("ttft_ms"), (float, int))]
    successes = len(measured)
    med = round(statistics.median(measured), 2) if measured else None
    return {
        "status": "measured" if records else "no_measurements",
        "samples": len(records), "successful": successes,
        "failed": len(records) - successes,
        "success_rate": round(successes / len(records), 4) if records else None,
        "ttft_ms": {"p50": med, "p95": percentile(measured, 95),
                    "p99": percentile(measured, 99), "min": round(min(measured), 2) if measured else None,
                    "max": round(max(measured), 2) if measured else None},
        "goal": {"metric": "median_ttft_ms", "target_ms": target_ms,
                 "evaluation": "insufficient_samples" if len(measured) < 30
                 else ("met" if med <= target_ms else "not_met")},
        "warning": "Fewer than 30 successful calls: not enough to assess target reliably" if len(measured) < 30 else None,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("RIZZLER_BENCH_MODEL", "gemini-3.5-flash-lite"))
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--cooldown-ms", type=int, default=1200)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--output", type=Path, default=Path("/tmp/rizzler_gemini_ttft.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("/tmp/rizzler_gemini_summary.json"))
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs without network or fabricated output")
    args = parser.parse_args(argv)
    if not MODEL_PATTERN.fullmatch(args.model):
        parser.error("Invalid Gemini model identifier")
    if not 1 <= args.repeat <= 30 or not 0 <= args.warmup <= 10:
        parser.error("--repeat 1..30 and --warmup 0..10 required")
    if not 0 <= args.cooldown_ms <= 30000 or not 1 <= args.timeout <= 300:
        parser.error("Invalid cooldown or timeout")
    prompts = load_prompts(args.prompts)
    if len(prompts) * args.repeat > 300:
        parser.error("Too many paid measured requests (max 300)")
    summary_config = {"model": args.model, "prompts": len(prompts), "repeat": args.repeat,
                      "warmup": args.warmup, "goal_ms": 564, "measurement": "request_to_first_visible_text"}
    if args.dry_run:
        print(json.dumps({"status": "configuration_validated_only", "live_requests": 0,
                          "performance_results": None, "configuration": summary_config}, indent=2))
        return 0
    key = get_secret()
    if not key:
        parser.error("GEMINI_API_KEY must be set as Kaggle Secret or environment variable")
    run_id = uuid.uuid4().hex
    for _ in range(args.warmup):
        _ = stream_gemini(prompts[0]["prompt"], args.model, key, args.timeout)
        if args.cooldown_ms:
            time.sleep(args.cooldown_ms / 1000)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    measurements = []
    with args.output.open("w", encoding="utf-8") as stream:
        for rep in range(args.repeat):
            for p in prompts:
                row = stream_gemini(p["prompt"], args.model, key, args.timeout)
                row.update({"event": "gemini_benchmark_request", "run_id": run_id,
                            "utc": datetime.now(timezone.utc).isoformat(), "model": args.model,
                            "prompt_id": p["id"], "prompt_chars": len(p["prompt"]), "repeat_index": rep,
                            "source": "live_rest_sse"})
                measurements.append(row)
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                stream.flush()
                if args.cooldown_ms:
                    time.sleep(args.cooldown_ms / 1000)
    result = {"run_id": run_id, "provenance": "live_gemini_api_rest_sse",
              "run_utc": datetime.now(timezone.utc).isoformat(), "configuration": summary_config,
              "statistics": summarize(measurements)}
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["statistics"]["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
