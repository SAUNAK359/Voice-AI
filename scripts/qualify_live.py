"""Qualify the modular voice app with a REAL WAV sample and real providers.

Kaggle: save GEMINI_API_KEY in Secrets; inject it into the environment in
the notebook's launcher cell. No API keys, transcripts or answer text are logged.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from rizzler.config import Settings
from rizzler.providers import GeminiLLM, KittenSpeech, WhisperASR
from rizzler.qualification import exercise, inspect_environment, read_pcm_wav
from rizzler.voice import ProviderSet, VoiceEngine


async def run(wav: Path, report: Path, require_cuda: bool, repetitions: int) -> bool:
    cfg = Settings.from_env()
    environment = inspect_environment(cfg, require_cuda=require_cuda)
    pcm, rate = read_pcm_wav(wav, cfg.max_audio_seconds)
    providers = ProviderSet(WhisperASR(cfg), GeminiLLM(cfg), KittenSpeech(cfg))
    engine = VoiceEngine(cfg, providers)
    outcomes = []
    try:
        for _ in range(repetitions):
            result = await exercise(engine, pcm, rate)
            outcomes.append(result)
            if result["outcome"] != "ok":
                break
    finally:
        await providers.llm.close()
    passed = len(outcomes) == repetitions and all(r["outcome"] == "ok" for r in outcomes)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"schema_version": 1, "verified": passed,
        "environment": environment, "runs": outcomes,
        "limitations": ["Does not measure browser microphone-to-first-audible latency",
                        "Does not certify noise robustness, concurrency or 17 Work Agent skills"]},
        indent=2) + "\n", encoding="utf-8")
    print(f"Voice qualification: {'PASS' if passed else 'FAIL'}; evidence: {report}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", type=Path, required=True, help="Mono PCM16 WAV, 0.2–22 seconds")
    parser.add_argument("--report", type=Path, default=Path("qualification-report.json"))
    parser.add_argument("--require-cuda", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 10:
        parser.error("--repeat must be 1–10")
    try:
        return 0 if asyncio.run(run(args.wav, args.report, args.require_cuda, args.repeat)) else 1
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        # Avoid dumping backend exception bodies or provider credentials.
        print(f"Qualification aborted: {type(exc).__name__}. Check dependencies, settings and recording.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
