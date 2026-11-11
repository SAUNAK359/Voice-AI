"""PCM conversion without a second audio stack. No implicit device resampling."""
from __future__ import annotations
import numpy as np


def pcm16_to_mono(raw: bytes, rate: int, limit_seconds: int = 22) -> np.ndarray:
    if not 8000 <= rate <= 96000:
        raise ValueError('Sample rate must be 8–96 kHz')
    if len(raw) % 2 or len(raw) < rate // 5 * 2:
        raise ValueError('Invalid or too-short PCM16 recording')
    if len(raw) > rate * limit_seconds * 2:
        raise ValueError('PCM16 recording exceeds duration limit')
    x = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0
    if rate == 16000:
        return x
    # Polyphase decimation is preferred for accurate ASR on 44.1/48 kHz browser audio.
    try:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(rate, 16000)
        return np.ascontiguousarray(resample_poly(x, 16000 // g, rate // g), dtype=np.float32)
    except ImportError:
        # A dependency-free fallback for local smoke tests, not the preferred
        # quality path for WER comparisons. `voice` extra installs SciPy.
        dst = int(len(x) * 16000 / rate)
        return np.interp(np.arange(dst) * rate / 16000, np.arange(len(x)), x).astype(np.float32)


def to_pcm16(wave, limit_seconds: int = 60, rate: int = 24000) -> bytes:
    x = np.asarray(wave, dtype=np.float32).reshape(-1)
    if x.size == 0 or x.size > rate * limit_seconds or not np.isfinite(x).all():
        raise ValueError('Invalid or unbounded TTS waveform')
    return (np.clip(x, -1, 1) * 32767).astype('<i2').tobytes()
