"""Validated application configuration. Secrets are never given to the browser."""
from __future__ import annotations
from dataclasses import dataclass
from os import environ
import re
import secrets


@dataclass(frozen=True)
class Settings:
    access_key: str
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_models: tuple[str, ...] = ()
    gemini_rpm: int = 12
    gemini_tpm: int = 24000
    gemini_max_attempts: int = 3
    gemini_quota_wait_seconds: float = 1.5
    gemini_enable_thinking: bool = False
    gemini_input_usd_per_million: float | None = None
    gemini_output_usd_per_million: float | None = None
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
        models = (self.gemini_model, *self.gemini_fallback_models)
        if (not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,99}", model) for model in models)
                or len(models) != len(set(models)) or len(models) > 4):
            raise ValueError("Invalid or duplicate Gemini model identifiers")
        if not 1 <= self.gemini_rpm <= 10000 or not 1 <= self.gemini_tpm <= 10_000_000:
            raise ValueError("Invalid local Gemini quotas")
        if not 1 <= self.gemini_max_attempts <= 5 or not 0 <= self.gemini_quota_wait_seconds <= 15:
            raise ValueError("Invalid retry/admission limits")
        if any(price is not None and (not 0 <= price <= 1000)
               for price in (self.gemini_input_usd_per_million, self.gemini_output_usd_per_million)):
            raise ValueError("Invalid Gemini cost configuration")
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
        fallback = tuple(part.strip() for part in
                         environ.get('RIZZLER_GEMINI_FALLBACK_MODELS', '').split(',')
                         if part.strip())
        def optional_price(name: str) -> float | None:
            value = environ.get(name, '').strip()
            return float(value) if value else None
        return cls(
            access_key=environ.get('RIZZLER_ACCESS_KEY', '') if
                environ.get('RIZZLER_DEPLOYMENT_MODE', 'demo') != 'production'
                else secrets.token_urlsafe(32),
            gemini_api_key=environ.get('GEMINI_API_KEY', ''),
            gemini_model=environ.get('RIZZLER_GEMINI_MODEL', 'gemini-3.5-flash-lite'),
            gemini_fallback_models=fallback,
            gemini_rpm=int(environ.get('RIZZLER_GEMINI_RPM', '12')),
            gemini_tpm=int(environ.get('RIZZLER_GEMINI_TPM', '24000')),
            gemini_max_attempts=int(environ.get('RIZZLER_GEMINI_MAX_ATTEMPTS', '3')),
            gemini_quota_wait_seconds=float(environ.get('RIZZLER_GEMINI_QUOTA_WAIT', '1.5')),
            gemini_enable_thinking=environ.get('RIZZLER_GEMINI_ENABLE_THINKING', '').lower() in ('1','true','yes'),
            gemini_input_usd_per_million=optional_price('RIZZLER_GEMINI_INPUT_USD_PER_MILLION'),
            gemini_output_usd_per_million=optional_price('RIZZLER_GEMINI_OUTPUT_USD_PER_MILLION'),
            asr_model=environ.get('RIZZLER_ASR_MODEL', 'large-v3-turbo'),
            asr_device=environ.get('RIZZLER_ASR_DEVICE', 'cpu'),
            tts_model=environ.get('RIZZLER_TTS_MODEL', 'KittenML/kitten-tts-nano-0.8'),
            tts_voice=environ.get('RIZZLER_TTS_VOICE', 'Bruno'))
