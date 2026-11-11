"""Live, app-native qualification of ASR → Gemini → TTS.

This deliberately measures server-submit-to-PCM, not browser first-audible.
It cannot mark Phase 2 browser-latency acceptance as passed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import wave
from pathlib import Path

from .config import Settings
from .voice import VoiceEngine


def inspect_environment(settings: Settings, require_cuda: bool = False) -> dict:
    modules = {"faster_whisper": "faster-whisper", "google.genai": "google-genai",
               "kittenml": "kittenml", "scipy": "scipy"}
    missing = []
    for module, package in modules.items():
        try:
            available = importlib.util.find_spec(module) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            missing.append(package)
    if missing:
        raise RuntimeError("Missing voice extras: " + ", ".join(missing))
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    devices = None
    if require_cuda or settings.asr_device == "cuda":
        import ctranslate2
        devices = ctranslate2.get_cuda_device_count()
        if devices < 1:
            raise RuntimeError("No CUDA device visible to CTranslate2")
        if settings.asr_device != "cuda":
            raise RuntimeError("RIZZLER_ASR_DEVICE must be cuda for a GPU qualification")
    return {"asr_device": settings.asr_device, "cuda_device_count": devices,
            "gemini_model": settings.gemini_model, "asr_model": settings.asr_model,
            "tts_model": settings.tts_model}


def read_pcm_wav(path: Path, max_seconds: int) -> tuple[bytes, int]:
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 5_000_000:
        raise ValueError("Recording missing or exceeds 5 MB")
    with wave.open(str(path), "rb") as file:
        if file.getnchannels() != 1 or file.getsampwidth() != 2 or file.getcomptype() != "NONE":
            raise ValueError("WAV must be mono uncompressed PCM16")
        rate, frames = file.getframerate(), file.getnframes()
        if not 8000 <= rate <= 96000 or not rate // 5 <= frames <= rate * max_seconds:
            raise ValueError("WAV sample rate or duration outside safe bounds")
        return file.readframes(frames), rate


async def exercise(engine: VoiceEngine, pcm: bytes, rate: int) -> dict:
    audio_bytes = 0
    final_text = ""
    transcript = ""
    metrics = None
    finished = False
    error = None
    async for event in engine.events(pcm, rate, []):
        kind = event["type"]
        if kind == "audio":
            data = event["data"]
            if not isinstance(data, bytes) or len(data) % 2:
                raise RuntimeError("Invalid audio chunk")
            audio_bytes += len(data)
        elif kind == "transcript":
            transcript = event["text"]
        elif kind == "assistant_text":
            final_text = event["text"]
        elif kind == "metrics":
            metrics = event["data"]
        elif kind == "done":
            finished = True
        elif kind == "error":
            error = event["code"]
    # Zero hallucinated successes: complete only with all three real stages.
    ok = bool(finished and transcript and final_text and audio_bytes and
              metrics and metrics.get("outcome") == "ok" and not error)
    return {"outcome": "ok" if ok else "failed",
            "error_code": error, "transcript_chars": len(transcript),
            "transcript_sha256": hashlib.sha256(transcript.encode()).hexdigest() if transcript else None,
            "answer_chars": len(final_text),
            "audio_bytes": audio_bytes, "audio_seconds": round(audio_bytes / (2 * engine.settings.sample_rate), 3),
            "metrics": metrics, "measurement": "server_submit_to_first_pcm_not_browser_audible"}
