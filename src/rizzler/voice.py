"""Bounded incremental speech pipeline with TTS overlapped with Gemini output."""
from __future__ import annotations
import asyncio
import secrets
import sqlite3
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from .audio import pcm16_to_mono
from .config import Settings
from .provider_types import ASRProvider, LLMProvider, TTSProvider
from .speech_text import for_speech


def phrases(text: str, flush: bool = False) -> tuple[list[str], str]:
    """Yield speakable phrases without emitting isolated single-word fragments."""
    parts = []
    while len(text) >= 20:
        ends = [i + 1 for i, c in enumerate(text[:110]) if c in '.!?;:' and i >= 17]
        stop = ends[0] if ends else (text.rfind(' ', 40, 90) if len(text) >= 90 else -1)
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
    asr: ASRProvider
    llm: LLMProvider
    tts: TTSProvider


class VoiceEngine:
    def __init__(self, settings: Settings, providers: ProviderSet, tools=None):
        self.settings, self.providers, self.tools = settings, providers, tools

    async def events(self, pcm: bytes, rate: int, history: list[dict], owner: str | None = None, sequence: int = 0, uploads: list[str] | None = None, nonce: str = '', visuals: list[str] | None = None, pdf_document: str | None = None) -> AsyncIterator[dict]:
        """Stream status, transcript, text, PCM16 and final metrics.

        A single producer and speech worker share bounded queues. On disconnect,
        both tasks are cancelled, and no completed result is recorded.
        """
        output: asyncio.Queue = asyncio.Queue(maxsize=48)
        start = time.perf_counter()
        trace = secrets.token_hex(8)  # Safe opaque ID, never a transcript hash.
        async def producer():
            worker = None
            try:
                async with asyncio.timeout(self.settings.request_timeout):
                    await output.put({'type': 'status', 'label': 'Transcribing'})
                    audio = pcm16_to_mono(pcm, rate, self.settings.max_audio_seconds)
                    asr_start = time.perf_counter()
                    transcript = await asyncio.to_thread(self.providers.asr.transcribe, audio)
                    asr_ms = (time.perf_counter() - asr_start) * 1000
                    if not isinstance(transcript,str) or len(transcript)>8000 or any(
                            ord(c)<32 and c not in '\n\t' for c in transcript):
                        raise ValueError('ASR transcript invalid or excessive')
                    await output.put({'type': 'transcript', 'text': transcript, 'final': True})
                    if not transcript:
                        raise ValueError('No clear speech recognized')
                    await output.put({'type': 'status', 'label': 'Generating response'})
                    speech_queue = asyncio.Queue(maxsize=5)
                    first_pcm_ms = None
                    tts_ms = 0.0
                    audio_bytes = 0
                    first_phrase_ms = None
                    async def speak():
                        nonlocal first_pcm_ms, tts_ms, audio_bytes, first_phrase_ms
                        begun = False
                        while True:
                            phrase = await speech_queue.get()
                            if phrase is None:
                                break
                            t0 = time.perf_counter()
                            if first_phrase_ms is None:
                                first_phrase_ms = (t0-start)*1000
                            for retry in range(2):
                                try:
                                    raw = await asyncio.wait_for(
                                        asyncio.to_thread(self.providers.tts.synthesize,phrase),
                                        timeout=min(16.0,self.settings.request_timeout/2))
                                    if (not isinstance(raw, bytes) or not raw or len(raw)%2 or
                                            len(raw)>self.settings.sample_rate*2*35):
                                        raise ValueError('TTS returned invalid PCM16')
                                    if not any(raw):
                                        raise ValueError('TTS returned silent PCM16')
                                    if getattr(self.providers.tts, "enforce_audibility", False):
                                        import numpy as np
                                        waveform = np.frombuffer(raw,dtype='<i2').astype(np.float32)
                                        if (float(np.sqrt(np.mean(waveform*waveform)))<40 or
                                                float(np.max(np.abs(waveform)))<80):
                                            raise ValueError('TTS returned inaudible PCM16')
                                    break
                                except (Exception, TimeoutError):
                                    if retry:
                                        raise ValueError('Speech synthesis unavailable') from None
                            tts_ms += (time.perf_counter() - t0) * 1000
                            if not begun:
                                begun = True
                                first_pcm_ms = (time.perf_counter() - start) * 1000
                                await output.put({'type': 'audio_begin', 'sample_rate': self.settings.sample_rate})
                            if audio_bytes + len(raw) > self.settings.sample_rate * 2 * 90:
                                raise ValueError('TTS response exceeds 90-second output budget')
                            audio_bytes += len(raw)
                            block = 960 * 2  # 40 ms @ 24 kHz, PCM16 mono
                            for i in range(0, len(raw), block):
                                await output.put({'type': 'audio', 'data': raw[i:i + block]})
                    worker = asyncio.create_task(speak(), name='rizzler-tts')
                    tool_result = None
                    if self.tools is not None and owner is not None:
                        from .voice_tools import classify_tool
                        intent = (None if getattr(self.tools, "agent", None) is not None else
                                  classify_tool(transcript, self.tools.store is not None))
                        if intent == 'web_search':
                            await output.put({'type':'status','label':'Searching verified sources'})
                            await speech_queue.put('I will check current sources.')
                        if intent == 'math':
                            await output.put({'type':'status','label':'Verifying the equations'})
                        if intent == 'work_submit':
                            await output.put({'type':'status','label':'Planning requested work'})
                            await speech_queue.put('I will organize the work into verified steps.')
                        tool_result = await self.tools.execute(transcript, owner, sequence, uploads=uploads, nonce=nonce, visuals=visuals,pdf_document=pdf_document,history=history)
                        if tool_result is not None:
                            await output.put({'type':'tool_result',
                                'tool':tool_result['tool'],
                                'verified':tool_result.get('verified',False),
                                'elapsed_ms':tool_result.get('tool_elapsed_ms'),
                                'job':tool_result.get('job'),
                                'approvals':tool_result.get('approvals',[])})
                    answer = ''
                    pending = ''
                    last_ui_ms, last_ui_len = 0.0, 0
                    first_text_ms = None
                    llm_started = time.perf_counter()
                    async def responses():
                        if tool_result is not None:
                            yield tool_result['text']
                        else:
                            memory = getattr(self.tools, "memory", None) if self.tools else None
                            if (memory is not None and owner is not None and
                                    hasattr(self.providers.llm, "stream_with_memory")):
                                try:
                                    facts = await asyncio.wait_for(
                                        asyncio.to_thread(memory.relevant,owner,transcript),
                                        timeout=1.5)
                                except (ValueError, OSError, RuntimeError, TimeoutError,
                                        sqlite3.DatabaseError):
                                    facts = []
                                source = self.providers.llm.stream_with_memory(
                                    transcript, history, facts)
                            else:
                                source = self.providers.llm.stream(transcript, history)
                            first = asyncio.create_task(anext(source), name='gemini-first-text')
                            try:
                                try:
                                    first_text = await asyncio.wait_for(asyncio.shield(first), timeout=1.2)
                                except asyncio.TimeoutError:
                                    # Wait for actual answer content rather than repeatedly
                                    # speaking generic filler under cloud model latency.
                                    first_text = await first
                                yield first_text
                                async for item in source:
                                    yield item
                            except StopAsyncIteration:
                                return
                            finally:
                                if not first.done():
                                    first.cancel()
                                await asyncio.gather(first, return_exceptions=True)

                    async for delta in responses():
                        if worker.done():
                            await worker  # propagate TTS failure promptly
                        if not delta:
                            continue
                        if first_text_ms is None:
                            first_text_ms = (time.perf_counter() - llm_started) * 1000
                        answer += delta
                        if len(answer) > 12000:
                            raise ValueError('Model output exceeded maximum response length')
                        t = time.perf_counter()
                        # Avoid resending and rerendering the entire cumulative
                        # transcript for each individual streaming token.
                        if t-last_ui_ms >= 0.12 or len(answer)-last_ui_len >= 120:
                            await output.put({'type': 'assistant_text', 'text': answer, 'final': False})
                            last_ui_ms, last_ui_len = t, len(answer)
                        if tool_result is None:
                            speakable, pending = phrases(pending + delta)
                            for phrase in speakable:
                                cleaned = for_speech(phrase)
                                if cleaned:
                                    await speech_queue.put(cleaned)
                    if not answer.strip():
                        raise ValueError('Gemini returned no visible response')
                    if tool_result is not None:
                        pending = tool_result['spoken']
                    speakable, pending = phrases(pending, flush=True)
                    for phrase in speakable:
                        cleaned = for_speech(phrase)
                        if cleaned:
                            await speech_queue.put(cleaned)
                    # Display text is independently usable even when speech
                    # synthesis later fails. Never mark the *audio* turn done
                    # until actual non-silent PCM has been produced.
                    await output.put({'type': 'assistant_text', 'text': answer, 'final': True})
                    await speech_queue.put(None)
                    await worker
                    if not audio_bytes:
                        raise ValueError('No TTS audio was produced')
                    await output.put({'type': 'metrics', 'data': {
                        'asr_ms': round(asr_ms, 2),
                        'llm_first_text_ms': round(first_text_ms, 2) if first_text_ms is not None and tool_result is None else None,
                        'tts_total_ms': round(tts_ms, 2),
                        'tts_first_phrase_ms': round(first_phrase_ms,2) if first_phrase_ms is not None else None,
                        'tts_first_phrase_to_pcm_ms': round(first_pcm_ms-first_phrase_ms,2)
                            if first_pcm_ms is not None and first_phrase_ms is not None else None,
                        'trace_id': trace,
                        'sequence':sequence,
                        'input_audio_seconds':round(len(pcm)/(rate*2),3),
                        'post_pause_first_audio_ms': round(first_pcm_ms, 2) if first_pcm_ms is not None else None,
                        'total_server_ms': round((time.perf_counter() - start) * 1000, 2),
                        'audio_bytes': audio_bytes,
                        'tool':tool_result['tool'] if tool_result else None,
                        'tool_ms':tool_result.get('tool_elapsed_ms') if tool_result else None,
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
