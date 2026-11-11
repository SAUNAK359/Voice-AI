"""Native FastAPI application (no notebook global variables)."""
from __future__ import annotations
import asyncio
import base64
import json
import secrets
import struct
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .config import Settings
from .providers import WhisperASR, GeminiLLM, KittenSpeech
from .sessions import Sessions
from .voice import VoiceEngine, ProviderSet
from .security import validate_session_id

WEB = Path(__file__).with_name('web')


def create_app(settings: Settings | None = None, providers: ProviderSet | None = None) -> FastAPI:
    cfg = settings or Settings.from_env()  # Fail closed without demo access key.
    models = providers or ProviderSet(WhisperASR(cfg), GeminiLLM(cfg), KittenSpeech(cfg))
    engine, sessions = VoiceEngine(cfg, models), Sessions()

    @asynccontextmanager
    async def lifespan(app):
        yield
        close = getattr(models.llm, 'close', None)
        if close:
            await close()
    app = FastAPI(title='Rizzler Voice AI', version='1.0.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.state.settings, app.state.sessions = cfg, sessions

    @app.middleware('http')
    async def protect_response(request: Request, call_next):
        response = await call_next(request)
        response.headers.update({
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; "
              "style-src 'self'; connect-src 'self' ws: wss:; img-src 'self'; "
              "worker-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        })
        return response

    def auth(request: Request, session_required: bool = False) -> str | None:
        token = request.headers.get('x-rizzler-key', '')
        if not secrets.compare_digest(token, cfg.access_key):
            raise HTTPException(status_code=401, detail='Invalid access key')
        if session_required:
            try:
                return validate_session_id(request.headers.get('x-session-id', ''))
            except ValueError:
                raise HTTPException(status_code=400, detail='Invalid session identifier')
        return None

    @app.get('/')
    def index():
        return FileResponse(WEB / 'index.html')

    app.mount('/static', StaticFiles(directory=WEB), name='static')

    @app.get('/health')
    def health():
        return {'ok': True, 'service': 'Rizzler', 'version': '1.0.0',
                'model_initialized': {
                    'asr': getattr(models.asr, '_model', None) is not None,
                    'gemini_client': getattr(models.llm, '_client', None) is not None,
                    'tts': getattr(models.tts, '_model', None) is not None,
                }, 'inference_busy': sessions.inference.locked(),
                'first_audio_claim': 'not_measured'}

    @app.get('/api/provider/metrics')
    def provider_metrics(request: Request):
        auth(request)
        stats = getattr(models.llm, 'telemetry', None)
        return stats.summary() if stats is not None else {
            'window_requests': 0, 'status': 'provider_telemetry_not_available'}

    @app.post('/api/auth')
    def authorize(request: Request):
        auth(request)
        return {'ok': True}

    @app.post('/api/reset')
    async def reset(request: Request):
        sid = auth(request, True)
        session = sessions.get(sid)
        await session.cancel()
        session.history.clear()
        session.generation += 1
        return {'ok': True}

    @app.post('/api/interrupt')
    async def interrupt(request: Request):
        sid = auth(request, True)
        session = sessions.sessions.get(sid)
        if session is None or session.task is None or session.task.done():
            return {'cancelled': False}
        await session.cancel()
        session.generation += 1
        return {'cancelled': True}

    @app.post('/api/turn')
    async def http_turn(request: Request):
        sid = auth(request, True)
        if sessions.inference.locked():
            raise HTTPException(status_code=409, detail='Model busy; retry')
        try:
            rate = int(request.headers.get('x-sample-rate', '48000'))
        except ValueError:
            raise HTTPException(status_code=400, detail='Invalid sample rate')
        # Hard bound before reading body; an arbitrary body is never buffered past cap.
        limit = min(5_000_000, rate * cfg.max_audio_seconds * 2) if 8000 <= rate <= 96000 else 0
        if not limit:
            raise HTTPException(status_code=400, detail='Invalid sample rate')
        content_length = request.headers.get('content-length')
        if content_length and content_length.isdigit() and int(content_length) > limit:
            raise HTTPException(status_code=413, detail='Audio too large')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > limit:
                raise HTTPException(status_code=413, detail='Audio too large')
        session = sessions.get(sid)
        generation = session.generation + 1
        session.generation = generation
        async with sessions.inference:
            task = asyncio.current_task()
            session.task = task
            events, samples = [], bytearray()
            try:
                async for event in engine.events(bytes(raw), rate, list(session.history)):
                    if generation != session.generation:
                        raise HTTPException(status_code=409, detail='Turn superseded')
                    if event['type'] == 'audio':
                        samples.extend(event['data'])
                    else:
                        events.append(event)
                failure = next((e for e in events if e['type'] == 'error'), None)
                if failure:
                    raise HTTPException(status_code=502, detail=failure['message'])
                last = next((e for e in reversed(events) if e['type'] == 'done'), None)
                if not last:
                    raise HTTPException(status_code=502, detail='Incomplete voice response')
                session.history = last['history']
                transcript = next((e['text'] for e in events if e['type'] == 'transcript'), '')
                answer = next((e['text'] for e in reversed(events) if e['type'] == 'assistant_text'), '')
                metrics = next((e['data'] for e in events if e['type'] == 'metrics'), {})
                return JSONResponse({'transcript': transcript, 'answer': answer,
                    'metrics': metrics, 'sample_rate': cfg.sample_rate,
                    'audio_b64': base64.b64encode(samples).decode('ascii')})
            finally:
                if session.task is task:
                    session.task = None

    @app.websocket('/ws')
    async def websocket(ws: WebSocket):
        origin = ws.headers.get('origin', '')
        expected = ws.headers.get('host', '')
        parsed = urlparse(origin)
        if parsed.scheme not in ('http', 'https') or parsed.netloc != expected:
            await ws.close(code=1008)
            return
        # Allow independent authenticated browser connections. Actual model
        # inference remains serialized by sessions.inference.
        session = None
        try:
            await ws.accept()
            try:
                first = await asyncio.wait_for(ws.receive_json(), 8)
                if first.get('type') != 'auth' or not secrets.compare_digest(
                    str(first.get('token', '')), cfg.access_key):
                    await ws.close(code=1008)
                    return
                sid = validate_session_id(first.get('client_id', ''))
                rate = int(first.get('sample_rate', 48000))
                if not 8000 <= rate <= 96000:
                    await ws.close(code=1008)
                    return
                session = sessions.get(sid)
                # One WebSocket per session: a second connection must not take
                # over or cancel an existing client's live speech.
                if session.websocket is not None:
                    await ws.close(code=1013)
                    return
                session.websocket = ws
            except (asyncio.TimeoutError, ValueError, TypeError, KeyError, RuntimeError):
                await ws.close(code=1008)
                return
            await ws.send_json({'type': 'ready', 'sample_rate': cfg.sample_rate})
            pcm = bytearray()
            recording = False
            async def stream_turn(recorded: bytes, seq: int):
                async with sessions.inference:
                    try:
                        async for event in engine.events(recorded, rate, list(session.history)):
                            if seq != session.generation:
                                return
                            if event['type'] == 'audio':
                                await ws.send_bytes(struct.pack('<I', seq) + event['data'])
                            else:
                                if event['type'] == 'done':
                                    session.history = event.pop('history')
                                await ws.send_json({'generation': seq, **event})
                    except WebSocketDisconnect:
                        return
            while True:
                data = await ws.receive()
                if data['type'] == 'websocket.disconnect':
                    break
                if data.get('bytes') is not None:
                    if recording:
                        raw = data['bytes']
                        if len(raw) <= 16384 and len(raw) % 2 == 0:
                            pcm.extend(raw)
                            if len(pcm) > rate * cfg.max_audio_seconds * 2:
                                recording = False
                                pcm.clear()
                                await ws.send_json({'type': 'error', 'generation': session.generation,
                                    'message': 'Audio duration limit exceeded'})
                    continue
                if not data.get('text'):
                    continue
                try:
                    msg = json.loads(data['text'])
                    kind = msg.get('type')
                    if kind == 'speech_start':
                        seq = int(msg.get('generation', -1))
                        if seq <= session.generation or seq > 2**31 - 1:
                            continue
                        await session.cancel()
                        session.generation = seq
                        pcm.clear()
                        recording = True
                        await ws.send_json({'type': 'status', 'generation': seq, 'label': 'Listening'})
                    elif kind == 'speech_end' and recording:
                        seq = int(msg.get('generation', -1))
                        if seq != session.generation:
                            continue
                        recording = False
                        if sessions.inference.locked():
                            await ws.send_json({'type': 'error', 'generation': seq, 'message': 'Model busy'})
                            continue
                        session.task = asyncio.create_task(stream_turn(bytes(pcm), seq), name='ws-voice-turn')
                        pcm.clear()
                    elif kind == 'interrupt':
                        await session.cancel()
                        # The browser increments generation on its next speech_start.
                        # Bumping it here would reject that first new utterance.
                        recording = False
                        pcm.clear()
                        await ws.send_json({'type': 'interrupted', 'generation': session.generation})
                    elif kind == 'new_conversation':
                        await session.cancel()
                        session.history.clear()
                        pcm.clear()
                        recording = False
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            if session and session.websocket is ws:
                await session.cancel()
                session.websocket = None

    return app


def _lazy_app():
    return create_app()

# uvicorn --factory rizzler.api:create_app is preferred: configuration is read
# at startup rather than import time, and CI imports have no secret dependency.
