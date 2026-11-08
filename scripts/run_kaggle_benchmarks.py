#!/usr/bin/env python3
"""Kaggle-only reproducible Rizzler benchmark runner.

Invoked from an authenticated private GitHub checkout. Produces redacted
JSON/JSONL summaries; no audio, utterance text, prompt or API credential is
written in the output directory. The calling notebook pushes those summaries.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import importlib.metadata
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from statistics import median
from math import ceil

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def pct(values, n):
    if not values:
        return None
    v = sorted(float(x) for x in values)
    return round(v[max(0, ceil(len(v) * n / 100) - 1)], 2)


def vers(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def gpu_metadata():
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("NVIDIA CUDA GPU required. Set Kaggle accelerator to GPU T4 x2 (or T4).")
    devices = []
    for i in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(i)
        devices.append({"index": i, "name": p.name,
                        "total_vram_gb": round(p.total_memory / 1024 ** 3, 2)})
    return {"torch_cuda_available": True, "devices": devices,
            "torch": torch.__version__, "torch_cuda_build": torch.version.cuda}


def nvidia_snapshot():
    try:
        r = subprocess.run([
            "nvidia-smi", "--query-gpu=index,memory.used,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10, check=True)
        rows = []
        for line in r.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 4:
                rows.append({"index": int(parts[0]), "used_mib": int(parts[1]),
                             "gpu_utilization_percent": int(parts[2]), "temperature_c": int(parts[3])})
        return rows
    except Exception:
        return []


def run_subprocess(cmd, cwd: Path):
    completed = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=1800)
    # No prompts or credentials should be printed by the repo benchmark utilities.
    return {"exit_code": completed.returncode,
            "stderr_tail": completed.stderr[-500:] if completed.returncode else ""}


def run_offline(out: Path):
    reports = {}
    jobs = {
        "synthetic_asr_scorer": [
            sys.executable, str(SCRIPTS / "score_asr.py"),
            "--input", str(ROOT / "benchmarks/fixtures/asr_synthetic_smoke.csv"),
            "--dataset-id", "synthetic_offline_smoke_not_real_asr_accuracy",
            "--output", str(out / "synthetic_asr_smoke.json")],
        "legacy_failed_turn_summary": [
            sys.executable, str(SCRIPTS / "benchmark.py"),
            str(ROOT / "benchmarks/data/legacy_failed_turn.jsonl"),
            "--output", str(out / "legacy_failed_turn_summary.json")],
        "artifact_structure": [
            sys.executable, str(SCRIPTS / "benchmark_artifacts.py"),
            str(ROOT / "examples"),
            "--output", str(out / "artifact_structure.json")],
    }
    for name, cmd in jobs.items():
        try:
            status = run_subprocess(cmd, ROOT)
            reports[name] = {"status": "completed" if status["exit_code"] == 0 else "failed",
                             "exit_code": status["exit_code"],
                             "note": "offline_fixture_or_legacy_trace_not_live_model_benchmark"}
        except Exception as exc:
            reports[name] = {"status": "error", "error_type": type(exc).__name__}
    return reports


def run_gemini(out: Path, model: str, repeat: int, cooldown_ms: int):
    cmd = [sys.executable, str(SCRIPTS / "benchmark_gemini.py"),
           "--model", model,
           "--prompts", str(ROOT / "benchmarks/fixtures/gemini_prompts.jsonl"),
           "--repeat", str(repeat), "--warmup", "2",
           "--cooldown-ms", str(cooldown_ms),
           "--output", str(out / "gemini_requests.jsonl"),
           "--summary", str(out / "gemini_summary.json")]
    try:
        status = run_subprocess(cmd, ROOT)
        summary = out / "gemini_summary.json"
        return {"status": "completed" if status["exit_code"] == 0 and summary.exists() else "failed",
                "exit_code": status["exit_code"], "model": model,
                "summary_available": summary.exists(),
                "measurement": "live_rest_stream_to_first_visible_text_not_audio"}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "model": model}


def decode_audio(example):
    """Decode streamed HF audio bytes or locally supplied voice clips using FFmpeg.

    Caches no decoded waveforms and writes no audio to the results tree.
    """
    import numpy as np
    if isinstance(example, dict) and "array" in example and "sampling_rate" in example:
        array = np.asarray(example["array"], dtype=np.float32)
        return array, int(example["sampling_rate"])
    raw = example.get("bytes") if isinstance(example, dict) else None
    path = example.get("path") if isinstance(example, dict) else str(example)
    if raw is None and (not path or not Path(path).is_file()):
        raise ValueError("Audio bytes/path unavailable")
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
    if raw is not None:
        cmd += ["-i", "pipe:0"]
    else:
        cmd += ["-i", str(path)]
    cmd += ["-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar", "16000", "pipe:1"]
    p = subprocess.run(cmd, input=raw, capture_output=True, timeout=90)
    if p.returncode or not p.stdout:
        raise RuntimeError("FFmpeg audio decode failed")
    return np.frombuffer(p.stdout, dtype="<f4").copy(), 16000


def streaming_corpus(dataset_id: str, config: str, split: str, reference_field: str, revision: str | None = None):
    from datasets import load_dataset, Audio
    it = load_dataset(dataset_id, config, split=split, streaming=True, revision=revision)
    if "audio" in it.features:
        it = it.cast_column("audio", Audio(decode=False))
    for row in it:
        reference = row.get(reference_field)
        audio = row.get("audio")
        if isinstance(reference, str) and reference.strip() and audio is not None:
            yield reference, audio


def common_voice_corpus(root: Path):
    """Only an authorized, user-attached Mozilla Data Collective dataset."""
    if not root.exists():
        return
    manifests = [root / "validated.tsv", root / "test.tsv"]
    if not any(p.is_file() for p in manifests):
        manifests = list(itertools.islice(root.rglob("validated.tsv"), 3))
    if not manifests:
        manifests = list(itertools.islice(root.rglob("test.tsv"), 3))
    if not manifests:
        return
    file = next(p for p in manifests if p.is_file())
    with file.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            reference = row.get("sentence")
            file_name = row.get("path") or row.get("clip")
            if not reference or not file_name:
                continue
            p = (file.parent / "clips" / file_name).resolve()
            # Enforce that a supplied TSV cannot escape its attached clips directory.
            clips = (file.parent / "clips").resolve()
            if clips not in p.parents or not p.is_file():
                continue
            yield reference, {"path": str(p), "bytes": None}


def assess_asr(out: Path, max_per_dataset: int, cv_root: Path | None, model_name: str):
    import numpy as np
    import torch
    from faster_whisper import WhisperModel
    from score_asr import score

    torch.cuda.reset_peak_memory_stats(0)
    model = WhisperModel(model_name, device="cuda", device_index=0, compute_type="float16")
    stats = {}
    datasets = [
        ("librispeech_test_clean", "openslr/librispeech_asr", "clean", "test", "text"),
        ("fleurs_en_us_test", "google/fleurs", "en_us", "test", "transcription"),
    ]

    def measure(name, rows, source):
        scored = []
        timings = []
        audio_s = 0.0
        failures = 0
        failure_types = {}
        failure_stages = {}
        failure_causes = {}
        for reference, audio in itertools.islice(rows, max_per_dataset):
            stage = "audio_decode"
            try:
                array, rate = decode_audio(audio)
                if rate != 16000:
                    raise RuntimeError("Expected 16 kHz resampled audio")
                duration = len(array) / rate
                if not 0.15 <= duration <= 60:
                    continue
                stage = "whisper_inference"
                t0 = time.perf_counter()
                segments, _ = model.transcribe(array, language="en", beam_size=1,
                                               condition_on_previous_text=False, vad_filter=False)
                prediction = " ".join(s.text.strip() for s in segments).strip()
                elapsed = (time.perf_counter() - t0) * 1000
                timings.append(elapsed)
                scored.append({"reference": reference, "hypothesis": prediction})
                audio_s += duration
            except Exception as exc:
                failures += 1
                kind = type(exc).__name__
                failure_types[kind] = failure_types.get(kind, 0) + 1
                failure_stages[stage] = failure_stages.get(stage, 0) + 1
                message = str(exc).lower()
                # Categorize errors without publishing source text, audio, file
                # paths or full exception messages into a public repository.
                if "cublas" in message or "cudnn" in message or "cudart" in message:
                    cause = "cuda12_library_missing_or_incompatible"
                elif "cuda" in message or "cud" in message:
                    cause = "cuda_runtime_error"
                elif "ffmpeg" in message or "decode" in message:
                    cause = "audio_decode_error"
                elif "out of memory" in message:
                    cause = "out_of_memory"
                else:
                    cause = "other_runtime_error"
                failure_causes[cause] = failure_causes.get(cause, 0) + 1
        if not scored:
            return {"status": "failed_no_audio_transcriptions", "dataset": source,
                    "errors": failures, "error_types": failure_types,
                    "failure_stages": failure_stages, "failure_causes": failure_causes,
                    "transcripts_or_audio_published": False}
        result = score(scored, dataset=name)
        result.update({"status": "measured_live_cuda_subset", "source": source,
                       "model": model_name, "device": "cuda:0", "sample_limit": max_per_dataset,
                       "audio_seconds": round(audio_s, 2),
                       "latency_ms_p50": round(median(timings), 2),
                       "latency_ms_p95": pct(timings, 95),
                       "real_time_factor": round(sum(timings) / 1000 / audio_s, 4) if audio_s else None,
                       "failed_or_skipped": failures, "failure_types": failure_types,
                       "failure_stages": failure_stages, "failure_causes": failure_causes,
                       "transcripts_or_audio_published": False})
        return result

    for label, ds, config, split, reference_field in datasets:
        print(f"ASR corpus: {label}", flush=True)
        try:
            revision = None
            try:
                from huggingface_hub import HfApi
                revision = HfApi().dataset_info(ds).sha
            except Exception:
                pass
            source = {"provider": "huggingface", "dataset": ds, "config": config, "split": split,
                      "revision_sha": revision,
                      "selection": "first N valid streamed utterances; small smoke subset"}
            rows = streaming_corpus(ds, config, split, reference_field, revision=revision)
            stats[label] = measure(label, rows, source)
        except Exception as exc:
            stats[label] = {"status": "unavailable", "dataset": ds,
                            "error_type": type(exc).__name__, "transcripts_or_audio_published": False}

    if cv_root is not None:
        try:
            rows = common_voice_corpus(cv_root)
            if rows is None:
                stats["common_voice_attached"] = {
                    "status": "not_run_missing_dataset", "note": "Attach licensed Common Voice files using Kaggle Add Data"}
            else:
                stats["common_voice_attached"] = measure("common_voice_attached", rows,
                    {"provider": "Mozilla Data Collective (user-provided copy)",
                     "manifest": "validated.tsv or test.tsv", "selection": "first N valid attached clips"})
        except Exception as exc:
            stats["common_voice_attached"] = {"status": "unavailable", "error_type": type(exc).__name__}
    else:
        stats["common_voice_attached"] = {"status": "not_run_missing_dataset",
                                          "note": "Mozilla Common Voice requires user-authorized download and Kaggle attachment"}
    stats["whisper_model"] = {"requested": model_name, "compute_type": "float16",
                               "cuda_device": 0, "torch_allocated_peak_mib": round(torch.cuda.max_memory_allocated(0) / (1024**2), 2),
                               "note": "Torch memory metric excludes CTranslate2 GPU allocations"}
    write_json(out / "asr_results.json", stats)
    return {"status": "completed", "datasets": {k: v.get("status", "metadata") for k, v in stats.items() if k != "whisper_model"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--gemini-model", default="gemini-3.5-flash-lite")
    parser.add_argument("--repeat", type=int, default=5, help="10 prompt fixtures x repeat; 5=50 measured requests")
    parser.add_argument("--cooldown-ms", type=int, default=1500)
    parser.add_argument("--asr-samples", type=int, default=20, help="samples per public ASR dataset")
    parser.add_argument("--whisper-model", default="turbo")
    parser.add_argument("--asr-only", action="store_true", help="Skip Gemini and offline tests; rerun CUDA ASR only")
    parser.add_argument("--common-voice-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.repeat <= 30 or not 1 <= args.asr_samples <= 200:
        parser.error("repeat must be 1..30 and ASR sample count 1..200")
    if not 0 <= args.cooldown_ms <= 30000:
        parser.error("Invalid cooldown value")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,99}", args.gemini_model):
        parser.error("Invalid Gemini model ID")
    if args.dry_run:
        print(json.dumps({"status": "configuration_validated_only", "gpu_required": True,
                          "gemini_requests": 10 * args.repeat + 2, "ASR_max_per_dataset": args.asr_samples,
                          "no_live_measurements_created": True}, indent=2))
        return 0
    if not args.asr_only and not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("Missing GEMINI_API_KEY; set it using Kaggle Secrets in the launch cell")
    gpu = gpu_metadata()
    out = args.output_dir.resolve()
    if out == ROOT or ROOT in out.parents:
        # Usually results live inside repo for Git publishing, which is allowed.
        pass
    out.mkdir(parents=True, exist_ok=False)  # never overwrite a historical run
    run_id = out.name
    try:
        git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        git_head = None
    report = {"run_id": run_id, "utc_start": stamp(), "git_base_commit": git_head,
              "source": "Kaggle NVIDIA CUDA T4 session with live Gemini and public dataset samples",
              "git_push": "performed_separately_by_user_Kaggle_cell",
              "machine": gpu, "nvidia_smi_before": nvidia_snapshot(),
              "libraries": {name: vers(name) for name in ["faster-whisper", "ctranslate2", "datasets", "numpy", "torch", "huggingface-hub"]},
              "benchmark_config": {"gemini_model": args.gemini_model,
                                   "measured_gemini_requests": args.repeat * 10,
                                   "gemini_warmups": 2,
                                   "asr_max_per_dataset": args.asr_samples,
                                   "common_voice_attached": bool(args.common_voice_root)},
              "jobs": {}}
    # Save a start marker for crash diagnosis; no private content.
    write_json(out / "run_manifest.json", report)
    if args.asr_only:
        report["jobs"]["offline"] = {"status": "skipped_by_configuration"}
        report["jobs"]["gemini"] = {"status": "skipped_by_configuration"}
        write_json(out / "run_manifest.json", report)
    else:
        print("1/3: Offline fixtures, legacy event and sample artifact validation", flush=True)
        report["jobs"]["offline"] = run_offline(out)
        write_json(out / "run_manifest.json", report)
        print("2/3: Gemini streaming time-to-first-visible-text benchmark", flush=True)
        report["jobs"]["gemini"] = run_gemini(out, args.gemini_model, args.repeat, args.cooldown_ms)
        write_json(out / "run_manifest.json", report)
    print("3/3: CUDA Whisper Turbo on LibriSpeech/FLEURS (+ optional Common Voice)", flush=True)
    try:
        report["jobs"]["asr"] = assess_asr(out, args.asr_samples, args.common_voice_root, args.whisper_model)
    except Exception as exc:
        report["jobs"]["asr"] = {"status": "failed", "error_type": type(exc).__name__}
    report["utc_end"] = stamp()
    report["nvidia_smi_after"] = nvidia_snapshot()
    report["safety"] = {"recorded_audio": False, "recorded_transcripts": False,
                        "recorded_prompts": False, "recorded_api_keys": False,
                        "benchmark_execution_is_not_end_to_end_browser_latency": True}
    write_json(out / "run_manifest.json", report)
    print(json.dumps({"result_dir": str(out), "statuses": report["jobs"],
                      "note": "Metric files must be committed by the authenticated Kaggle launch cell"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
