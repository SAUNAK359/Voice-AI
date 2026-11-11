"""Thin adapters around existing ASR/Gemini/TTS providers.

Imports of heavy optional dependencies happen on first use, not API startup.
ASR/TTS model and native kernels use persistent thread locks so cancellation
cannot start concurrent kernels after a to_thread() waiter is cancelled.
"""
from __future__ import annotations
import asyncio
import random
import threading
from typing import AsyncIterator
from .config import Settings


class WhisperASR:
    def __init__(self, settings: Settings):
        self.settings, self._model, self._lock = settings, None, threading.Lock()

    def transcribe(self, waveform) -> str:
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise RuntimeError("Install voice extras: pip install -e '.[voice]'") from exc
                self._model = WhisperModel(self.settings.asr_model,
                    device=self.settings.asr_device,
                    compute_type='float16' if self.settings.asr_device == 'cuda' else 'int8',
                    cpu_threads=4, num_workers=1)
            segments, _ = self._model.transcribe(waveform, language='en', beam_size=1,
                condition_on_previous_text=False, vad_filter=False)
            return ' '.join(segment.text.strip() for segment in segments).strip()


class GeminiLLM:
    def __init__(self, settings: Settings):
        self.settings, self._client = settings, None

    async def stream(self, user_text: str, history: list[dict]) -> AsyncIterator[str]:
        if not self.settings.gemini_api_key:
            raise RuntimeError('Missing GEMINI_API_KEY')
        if self._client is None:
            try:
                from google import genai
            except ImportError as exc:
                raise RuntimeError("Install voice extras: pip install -e '.[voice]'") from exc
            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        # Keep only bounded plain role/text turns in the system prompt.
        context = '\n'.join(f"{t['role']}: {str(t['content'])[:900]}"
            for t in history[-6:] if t.get('role') in ('user', 'assistant'))
        instructions = ('You are Rizzler, a concise, helpful voice assistant. '
            'Give accurate, naturally spoken answers. Do not invent tool usage. '
            'Keep ordinary answers under three sentences.')
        content = f'{instructions}\nPrior dialog:\n{context}\nUser: {user_text[:1600]}\nAssistant:'
        from google.genai import types
        # Retry 429/503 only before any text was streamed. Once output starts,
        # retrying could duplicate content the user has already heard.
        for attempt in range(3):
            visible = False
            try:
                stream = await self._client.aio.models.generate_content_stream(
                    model=self.settings.gemini_model, contents=content,
                    config=types.GenerateContentConfig(temperature=0.35, max_output_tokens=350))
                async for chunk in stream:
                    text = str(getattr(chunk, 'text', '') or '')
                    if text:
                        visible = True
                        yield text
                return
            except Exception as exc:
                error = str(exc).lower()
                transient = any(s in error for s in ('429', '503', 'resource_exhausted', 'unavailable'))
                if visible or attempt == 2 or not transient:
                    raise
                await asyncio.sleep(min(3.0, (2 ** attempt) * 0.75 + random.random() * 0.15))

    async def close(self):
        if self._client is not None:
            await self._client.aio.aclose()
            self._client = None


class KittenSpeech:
    def __init__(self, settings: Settings):
        self.settings, self._model, self._lock = settings, None, threading.Lock()

    def synthesize(self, text: str) -> bytes:
        from .audio import to_pcm16
        with self._lock:
            if self._model is None:
                try:
                    from kittenml import KittenTTS
                except ImportError as exc:
                    raise RuntimeError("Install voice extras: pip install -e '.[voice]'") from exc
                self._model = KittenTTS(self.settings.tts_model, backend='cpu')
            generator = getattr(getattr(self._model, 'model', None), 'generate', None)
            if generator is None:
                generator = self._model.generate
            # This is the verified legacy V9 Kitten Nano interface.
            return to_pcm16(generator(text, voice=self.settings.tts_voice, speed=1.18),
                            rate=self.settings.sample_rate)
