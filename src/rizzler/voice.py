"""Bounded incremental speech pipeline with TTS overlapped with Gemini output."""
from __future__ import annotations
import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from .audio import pcm16_to_mono
from .config import Settings


def phrases(text: str, flush: bool = False) -> tuple[list[str], str]:
    """Yield speakable phrases without emitting isolated single-word fragments."""
    parts = []
    while len(text) >= 32:
        ends = [i + 1 for i, c in enumerate(text[:125]) if c in '.!?;:' and i >= 27]
        stop = ends[0] if ends else (text.rfind(' ', 50, 110) if len(text) >= 110 else -1)
        if stop <= 0:
            break
        parts.append(text[:stop].strip())
        text = text[stop:].lstrip()
    if flush and text.strip():
        parts.append(text.strip())
        text = ''
    return parts, text


@dataclass
class ProviderSet:
    asr: object
    llm: object
    tts: object


class VoiceEngine:
    def __init__(self, settings: Settings, providers: ProviderSet):
        self.settings, self.providers = settings, providers

    async def events(self, pcm: bytes, rate: int, history: list[dict]) -> AsyncIterator[dict]:
        """Stream status, transcript, text, PCM16 and final metrics.

        A single producer and speech worker share bounded queues. On disconnect,
        both tasks are cancelled, and no completed result is recorded.
        """
        output: asyncio.Queue = asyncio.Queue(maxsize=48)
        start = time.perf_counter()
        async def producer():
            worker = None
            try:
                async with asyncio.timeout(self.settings.request_timeout):
                    await output.put({'type': 'status', 'label': 'Transcribing'})
                    audio = pcm16_to_mono(pcm, rate, self.settings.max_audio_seconds)
                    asr_start = time.perf_counter()
                    transcript = await asyncio.to_thread(self.providers.asr.transcribe, audio)
                    asr_ms = (time.perf_counter() - asr_start) * 1000
                    await output.put({'type': 'transcript', 'text': transcript, 'final': True})
                    if not transcript:
                        raise ValueError('No clear speech recognized')
                    await output.put({'type': 'status', 'label': 'Generating response'})
                    speech_queue = asyncio.Queue(maxsize=5)
                    first_pcm_ms = None
                    tts_ms = 0.0
                    audio_bytes = 0
                    async def speak():
                        nonlocal first_pcm_ms, tts_ms, audio_bytes
                        begun = False
                        while True:
                            phrase = await speech_queue.get()
                            if phrase is None:
                                break
                            t0 = time.perf_counter()
                            raw = await asyncio.to_thread(self.providers.tts.synthesize, phrase)
                            tts_ms += (time.perf_counter() - t0) * 1000
                            if not isinstance(raw, bytes) or not raw or len(raw) % 2:
                                raise ValueError('TTS returned empty/invalid PCM16')
                            if not begun:
                                begun = True
                                first_pcm_ms = (time.perf_counter() - start) * 1000
                                await output.put({'type': 'audio_begin', 'sample_rate': self.settings.sample_rate})
                            audio_bytes += len(raw)
                            block = 960 * 2  # 40 ms @ 24 kHz, PCM16 mono
                            for i in range(0, len(raw), block):
                                await output.put({'type': 'audio', 'data': raw[i:i + block]})
                    worker = asyncio.create_task(speak(), name='rizzler-tts')
                    answer = ''
                    pending = ''
                    first_text_ms = None
                    llm_started = time.perf_counter()
                    async for delta in self.providers.llm.stream(transcript, history):
                        if worker.done():
                            await worker  # propagate TTS failure promptly
                        if not delta:
                            continue
                        if first_text_ms is None:
                            first_text_ms = (time.perf_counter() - llm_started) * 1000
                        answer += delta
                        if len(answer) > 12000:
                            raise ValueError('Model output exceeded maximum response length')
                        await output.put({'type': 'assistant_text', 'text': answer, 'final': False})
                        speakable, pending = phrases(pending + delta)
                        for phrase in speakable:
                            await speech_queue.put(phrase)
                    if not answer.strip():
                        raise ValueError('Gemini returned no visible response')
                    speakable, pending = phrases(pending, flush=True)
                    for phrase in speakable:
                        await speech_queue.put(phrase)
                    await speech_queue.put(None)
                    await worker
                    if not audio_bytes:
                        raise ValueError('No TTS audio was produced')
                    await output.put({'type': 'assistant_text', 'text': answer, 'final': True})
                    await output.put({'type': 'metrics', 'data': {
                        'asr_ms': round(asr_ms, 2),
                        'llm_first_text_ms': round(first_text_ms, 2) if first_text_ms is not None else None,
                        'tts_total_ms': round(tts_ms, 2),
                        'post_pause_first_audio_ms': round(first_pcm_ms, 2) if first_pcm_ms is not None else None,
                        'total_server_ms': round((time.perf_counter() - start) * 1000, 2),
                        'audio_bytes': audio_bytes,
                        'measurement': 'server_submit_to_first_pcm_not_browser_audible',
                        'outcome': 'ok',
                    }})
                    new_history = (history + [{'role': 'user', 'content': transcript},
                        {'role': 'assistant', 'content': answer}])[-8:]
                    await output.put({'type': 'done', 'history': new_history})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Do not return arbitrary provider exception bodies (could contain
                # user content, prompts or credentials) to the browser.
                await output.put({'type': 'error', 'code': type(exc).__name__,
                                  'message': 'Voice processing failed; inspect server diagnostics.'})
            finally:
                if worker and not worker.done():
                    worker.cancel()
                if worker:
                    await asyncio.gather(worker, return_exceptions=True)
                await output.put({'type': '_end'})
        task = asyncio.create_task(producer(), name='rizzler-voice-turn')
        try:
            while True:
                item = await output.get()
                if item['type'] == '_end':
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
