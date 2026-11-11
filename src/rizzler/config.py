"""Validated application configuration. Secrets are never given to the browser."""
from __future__ import annotations
from dataclasses import dataclass
from os import environ


@dataclass(frozen=True)
class Settings:
    access_key: str
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    asr_model: str = "large-v3-turbo"
    asr_device: str = "cpu"   # Set cuda on a configured NVIDIA host.
    tts_model: str = "KittenML/kitten-tts-nano-0.8"
    tts_voice: str = "Bruno"
    sample_rate: int = 24000
    max_audio_seconds: int = 22
    request_timeout: float = 45.0
    max_concurrent_turns: int = 1

    def __post_init__(self):
        if len(self.access_key) < 16 or self.access_key.startswith('<'):
            raise ValueError('RIZZLER_ACCESS_KEY must contain at least 16 private characters')
        if self.asr_device not in ('cpu', 'cuda'):
            raise ValueError('RIZZLER_ASR_DEVICE must be cpu or cuda')
        if not 8 <= self.max_audio_seconds <= 120 or not 10 <= self.request_timeout <= 180:
            raise ValueError('Unsafe audio duration or request timeout')
        if self.sample_rate != 24000:
            raise ValueError('Rizzler phase-0 browser protocol requires 24 kHz speech output')
        if self.max_concurrent_turns != 1:
            raise ValueError('Phase-0 supports one inference turn at a time')

    @classmethod
    def from_env(cls) -> Settings:
        return cls(access_key=environ.get('RIZZLER_ACCESS_KEY', ''),
                   gemini_api_key=environ.get('GEMINI_API_KEY', ''),
                   gemini_model=environ.get('RIZZLER_GEMINI_MODEL', 'gemini-3.5-flash-lite'),
                   asr_model=environ.get('RIZZLER_ASR_MODEL', 'large-v3-turbo'),
                   asr_device=environ.get('RIZZLER_ASR_DEVICE', 'cpu'),
                   tts_model=environ.get('RIZZLER_TTS_MODEL', 'KittenML/kitten-tts-nano-0.8'),
                   tts_voice=environ.get('RIZZLER_TTS_VOICE', 'Bruno'))
