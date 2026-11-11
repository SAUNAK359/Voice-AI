"""Structural contracts for interchangeable speech/model adapters.

Kept dependency-free so fake providers can be used in CI and CPU smoke tests.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


class ASRProvider(Protocol):
    def transcribe(self, waveform: Any) -> str: ...


class LLMProvider(Protocol):
    def stream(self, user_text: str, history: list[dict]) -> AsyncIterator[str]: ...


class TTSProvider(Protocol):
    def synthesize(self, text: str) -> bytes: ...
