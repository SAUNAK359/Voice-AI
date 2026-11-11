"""Native FastAPI application (no notebook global variables)."""
from __future__ import annotations
import asyncio
import base64
import json
import secrets
import struct
import time
from contextlib import asynccontextmanager
from pathlib import Path
from os import environ
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from .config import Settings
from .providers import WhisperASR, GeminiLLM, KittenSpeech
from .sessions import Sessions
from .voice import VoiceEngine, ProviderSet
from .security import validate_session_id
from .identity import Identity, OIDCSettings
from .operations import Operations

WEB = Path(__file__).with_name('web')


def create_app(settings: Settings | None = None, providers: ProviderSet | None = None) -> FastAPI:
    mode = environ.get("RIZZLER_DEPLOYMENT_MODE", "demo").lower()
    if mode not in ("demo", "production"):
        raise ValueError("Invalid deployment mode")
    production = mode == "production"
    cfg = settings or Settings.from_env()
    models = providers or ProviderSet(WhisperASR(cfg), GeminiLLM(cfg), KittenSpeech(cfg))
    engine, sessions = VoiceEngine(cfg, models), Sessions()
    operations = Operations()
    ops_token = environ.get("RIZZLER_OPERATIONS_TOKEN", "")
    if production and (len(ops_token) < 32 or ops_token == environ.get("RIZZLER_SESSION_SIGNING_KEY", "")):
        raise ValueError("Production requires an independent operations secret")
    work_root = environ.get("RIZZLER_WORK_ROOT", "")
    work_signing_key = environ.get("RIZZLER_WORK_SIGNING_KEY", "")
    if bool(work_root) != bool(work_signing_key):
        raise ValueError("Configure both RIZZLER_WORK_ROOT and RIZZLER_WORK_SIGNING_KEY")
    if production and (not work_root or not work_signing_key):
        raise ValueError("Production requires durable Work Agent storage and signing key")
    identity = None
    if production:
        if not Path(work_root).is_absolute():
            raise ValueError("Production work root must be absolute")
        keys = ("ISSUER", "AUTHORIZE_URL", "TOKEN_URL", "JWKS_URL",
                "CLIENT_ID", "REDIRECT_URI")
        values = {key.lower(): environ.get("RIZZLER_OIDC_" + key, "") for key in keys}
        identity = Identity(
            OIDCSettings(**values, client_secret=environ.get("RIZZLER_OIDC_CLIENT_SECRET", "")),
            Path(work_root), environ.get("RIZZLER_SESSION_SIGNING_KEY", ""))
    if work_root:
        if environ.get("RIZZLER_DATABASE_URL"):
            from .work_postgres import PostgresWorkStore as WorkStore
        else:
            from .work_store import WorkStore
        from .work_auth import _secret
        _secret(work_signing_key)
        if production:
            from .upload_scan import scan_clamd
            scanner_host = environ.get("RIZZLER_CLAMD_HOST", "")
            if not scanner_host:
                raise ValueError("Production requires RIZZLER_CLAMD_HOST")
            try:
                scanner_port = int(environ.get("RIZZLER_CLAMD_PORT", "3310"))
            except ValueError:
                raise ValueError("Invalid malware scanner port") from None
            def scanner(data):
                return scan_clamd(data, scanner_host, scanner_port)
            work = (WorkStore(work_root, environ["RIZZLER_DATABASE_URL"], upload_scanner=scanner)
                    if environ.get("RIZZLER_DATABASE_URL") else
                    WorkStore(work_root, upload_scanner=scanner))
        else:
            work = (WorkStore(work_root, environ["RIZZLER_DATABASE_URL"])
                    if environ.get("RIZZLER_DATABASE_URL") else WorkStore(work_root))
    else:
        work = None

    @asynccontextmanager
    async def lifespan(app):
        yield
        close = getattr(models.llm, 'close', None)
        if close:
            await close()
    app = FastAPI(title='Rizzler Voice AI', version='1.0.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.state.settings, app.state.sessions = cfg, sessions
    app.state.operations = operations
    app.state.work, app.state.identity = work, identity
    app.state.production = production
    if work:
        from .work_api import router
        app.include_router(router(work, work_signing_key, identity=identity))

        @app.get('/work')
        def work_dashboard():
            return FileResponse(WEB / 'work.html')

    @app.middleware('http')
    async def protect_response(request: Request, call_next):
        began = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            operations.record(request.method, "unhandled", 500,
                              (time.perf_counter()-began)*1000)
            raise
        route = request.scope.get("route")
        operations.record(request.method, getattr(route, "path", "unknown"),
                          response.status_code, (time.perf_counter()-began)*1000)
        response.headers.update({
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; "
              "style-src 'self'; connect-src 'self' ws: wss:; img-src 'self'; "
              "worker-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        })
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    def auth(request: Request, session_required: bool = False) -> str | None:
        if identity is not None:
            return identity.owner(request, mutate=request.method not in ("GET", "HEAD", "OPTIONS"))
        token = request.headers.get('x-rizzler-key', '')
        if not secrets.compare_digest(token, cfg.access_key):
            raise HTTPException(status_code=401, detail='Invalid access key')
        if session_required:
            try:
                return validate_session_id(request.headers.get('x-session-id', ''))
            except ValueError:
                raise HTTPException(status_code=400, detail='Invalid session identifier')
        return None

    @app.get('/internal/metrics')
    def internal_metrics(request: Request):
        presented = request.headers.get("authorization", "")
        expected = "Bearer " + ops_token
        if not ops_token or not secrets.compare_digest(presented, expected):
            raise HTTPException(status_code=401, detail="Unauthorized") from None
        return operations.snapshot()

    @app.get('/ready')
    def ready():
        try:
            if production and (identity is None or work is None):
                raise RuntimeError("Required services unavailable")
            if work:
                with work._tx() as db:
                    db.execute("SELECT 1").fetchone()
            if identity:
                with identity.sessions._db() as db:
                    db.execute("SELECT 1").fetchone()
            return {"ready": True, "mode": mode}
        except Exception:
            raise HTTPException(status_code=503, detail="Dependency not ready") from None

    @app.get('/api/runtime')
    def runtime():
        return {"mode": mode, "work_enabled": work is not None}

    if identity is not None:
        @app.get('/auth/login')
        def login():
            return identity.login()

        @app.get('/auth/callback')
        async def callback(request: Request):
            params = request.query_params
            try:
                token, csrf = await identity.exchange(
                    params.get("code", ""), params.get("state", ""),
                    request.cookies.get("rizzler_oidc_flow", ""), params.get("iss"))
            except Exception:
                # Never expose provider tokens, exception bodies or identity details.
                raise HTTPException(status_code=401, detail="Identity verification failed") from None
            response = RedirectResponse("/", status_code=303)
            identity._cookies(response, token, csrf)
            response.delete_cookie("rizzler_oidc_flow", path="/", secure=True, samesite="lax")
            return response

        @app.get('/auth/session')
        def session_status(request: Request):
            owner = identity.owner(request)
            return {"authenticated": True, "mode": "production", "subject": owner}

        @app.post('/auth/refresh')
        def refresh(request: Request):
            identity.owner(request, mutate=True)
            try:
                token, csrf = identity.sessions.rotate(
                    request.cookies.get("rizzler_session", ""),
                    request.headers.get("x-csrf-token", ""))
            except PermissionError:
                raise HTTPException(status_code=401, detail="Session expired") from None
            response = JSONResponse({"refreshed": True})
            identity._cookies(response, token, csrf)
            return response

        @app.post('/auth/logout')
        def logout(request: Request):
            identity.owner(request, mutate=True)
            identity.sessions.revoke(request.cookies.get("rizzler_session", ""))
            response = JSONResponse({"logged_out": True})
            identity.clear_cookies(response)
            return response

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
                if first.get('type') != 'auth':
                    await ws.close(code=1008)
                    return
                if identity is not None:
                    try:
                        sid = identity.ws_owner(ws)
                    except PermissionError:
                        await ws.close(code=1008)
                        return
                else:
                    if not secrets.compare_digest(str(first.get('token', '')), cfg.access_key):
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
