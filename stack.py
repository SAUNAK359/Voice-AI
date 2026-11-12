#!/usr/bin/env python3
"""Rizzler public showcase + single-session, expiring GPU demonstration gateway.

Standard Colab cannot be silently started by a remote web visitor. This app
uses an explicitly configured, prebuilt RunPod v2 GPU image for automation,
with an optional link to a manually launched Colab notebook.

Install: pip install 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1' 'httpx>=0.27,<1' 'websockets>=14,<16'
Run:     python stack.py serve

All billable operations require an explicit POST from a browser with an origin
and visitor session cookie. Public GETs, link previews and crawlers never start
GPU compute. Single-process gateway; operator configures HTTPS at trusted edge.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import hmac
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

BASE = Path(__file__).resolve().parent
SITE = BASE / 'stack_site.html'
SITE_JS = BASE / 'stack_site.js'
MAX_SECONDS = 1800
DONE = ('ended', 'failed')
ACTIVE = ('starting', 'running', 'stopping')
COOKIE = 'rizzler_demo_visit'
POD_ID = re.compile(r'^[a-zA-Z0-9_-]{5,64}$')
NAME_ID = re.compile(r'^rizzler-portfolio-[a-f0-9]{20}$')
DEMO_DUMMY = 'RIZZLER_PORTFOLIO_DEMO'


@dataclass(frozen=True)
class Config:
    origin: str
    key: str
    db_path: Path
    mode: str = 'disabled'  # disabled, mock, runpod
    runpod_api_key: str = ''
    image: str = ''
    gemini_key: str = ''
    gpu: str = 'NVIDIA RTX A4000'  # 16 GB; RunPod does not list a T4.
    gpu_port: int = 8000
    registry_id: str = ''
    daily_limit: int = 3
    per_ip_limit: int = 2
    retention_days: int = 7
    trusted_proxies: tuple[str, ...] = ()
    colab_url: str = ''
    listen_host: str = '127.0.0.1'
    listen_port: int = 8787

    def __post_init__(self):
        parsed = urlparse(self.origin)
        if (parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.path not in ('', '/') or
                parsed.query or parsed.fragment or parsed.username or parsed.password):
            raise ValueError('STACK_PUBLIC_ORIGIN must be an exact origin')
        if parsed.scheme != 'https' and parsed.hostname not in ('localhost', '127.0.0.1', 'testserver'):
            raise ValueError('Public demo requires HTTPS')
        if len(self.key.encode()) < 32:
            raise ValueError('STACK_MASTER_KEY must be at least 32 bytes')
        if self.mode not in ('disabled', 'mock', 'runpod'):
            raise ValueError('Invalid provider mode')
        if self.mode == 'runpod' and not (self.runpod_api_key and self.image and self.gemini_key):
            raise ValueError('RunPod needs API key, prebuilt image, and Gemini key')
        if not 8000 <= self.gpu_port <= 65535:
            raise ValueError('Invalid GPU port')
        if not 1 <= self.daily_limit <= 20 or not 1 <= self.per_ip_limit <= self.daily_limit:
            raise ValueError('Invalid daily demo limits')
        if not 1 <= self.retention_days <= 30:
            raise ValueError('Privacy log retention must be 1-30 days')
        if self.colab_url and (urlparse(self.colab_url).scheme != 'https' or
                               not urlparse(self.colab_url).hostname):
            raise ValueError('Colab notebook URL must use HTTPS')

    @classmethod
    def env(cls):
        home = Path(os.environ.get('STACK_DATA_DIR', str(BASE / '.stack_data'))).resolve()
        return cls(
            origin=os.environ.get('STACK_PUBLIC_ORIGIN', 'http://127.0.0.1:8787').rstrip('/'),
            key=os.environ.get('STACK_MASTER_KEY', ''), db_path=home / 'sessions.sqlite3',
            mode=os.environ.get('STACK_PROVIDER', 'disabled'),
            runpod_api_key=os.environ.get('RUNPOD_API_KEY', ''),
            image=os.environ.get('STACK_POD_IMAGE', ''),
            gemini_key=os.environ.get('GEMINI_API_KEY', ''),
            gpu=os.environ.get('STACK_GPU_ID', 'NVIDIA RTX A4000'),
            gpu_port=int(os.environ.get('STACK_GPU_PORT', '8000')),
            registry_id=os.environ.get('STACK_RUNPOD_REGISTRY_ID', ''),
            daily_limit=int(os.environ.get('STACK_DAILY_LIMIT', '3')),
            per_ip_limit=int(os.environ.get('STACK_IP_LIMIT', '2')),
            retention_days=int(os.environ.get('STACK_LOG_RETENTION_DAYS', '7')),
            trusted_proxies=tuple(x.strip() for x in os.environ.get('STACK_TRUSTED_PROXY_IPS', '').split(',') if x.strip()),
            colab_url=os.environ.get('STACK_COLAB_NOTEBOOK_URL', ''),
            listen_host=os.environ.get('STACK_HOST', '127.0.0.1'),
            listen_port=int(os.environ.get('STACK_PORT', '8787')),
        )


class Database:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.tx() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS leases(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, ip TEXT NOT NULL,
                    status TEXT NOT NULL, pod_id TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL, expires REAL NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '', stop_attempts INTEGER NOT NULL DEFAULT 0,
                    updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS lease_active ON leases(status,expires);
                CREATE TABLE IF NOT EXISTS visit_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                    ip TEXT NOT NULL, ua TEXT NOT NULL,
                    referrer_host TEXT NOT NULL, event TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS visit_t ON visit_events(ts,event);
            ''')

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA busy_timeout=20000')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def events(self, ip: str, ua: str, ref: str, event: str, retention: int):
        now = time.time()
        with self.tx() as db:
            db.execute('INSERT INTO visit_events(ts,ip,ua,referrer_host,event) VALUES(?,?,?,?,?)',
                       (now, ip[:48], ua[:200], ref[:120], event))
            db.execute('DELETE FROM visit_events WHERE ts<?', (now - retention * 86400,))


class RunPod:
    """RunPod REST API v2 only; provider account, credentials and image stay server-side."""
    API = 'https://api.runpod.io/v2'

    def __init__(self, cfg: Config):
        self.cfg = cfg

    async def _call(self, method, path, payload=None):
        if not path.startswith('/pods'):
            raise ValueError('Restricted provider API path')
        async with httpx.AsyncClient(timeout=18, follow_redirects=False) as client:
            response = await client.request(method, self.API + path, json=payload,
                   headers={'Authorization': 'Bearer ' + self.cfg.runpod_api_key,
                            'Content-Type': 'application/json'})
            response.raise_for_status()
            return response.json() if response.content else {}

    async def create(self, name: str, env: dict) -> str:
        body = {
            'name': name, 'image': self.cfg.image,
            'gpu': {'id': self.cfg.gpu, 'count': 1},
            'disk': 35, 'ports': [f'{self.cfg.gpu_port}/http'],
            'env': env,
            **({'registry': self.cfg.registry_id} if self.cfg.registry_id else {}),
        }
        pod = await self._call('POST', '/pods', body)
        pod_id = pod.get('id', '')
        if not POD_ID.fullmatch(pod_id):
            raise RuntimeError('GPU provider returned no valid pod identifier')
        return pod_id

    async def find_named(self, name: str):
        result = await self._call('GET', '/pods')
        rows = result if isinstance(result, list) else result.get('pods', result.get('items', []))
        if not isinstance(rows, list):
            return None
        for pod in rows:
            if pod.get('name') == name and POD_ID.fullmatch(str(pod.get('id', ''))):
                return pod['id']
        return None

    async def state(self, pod_id):
        return await self._call('GET', '/pods/' + pod_id)

    async def terminate(self, pod_id):
        await self._call('DELETE', '/pods/' + pod_id)

    def url(self, pod_id):
        if not POD_ID.fullmatch(pod_id):
            raise ValueError('Bad provider pod identifier')
        return f'https://{pod_id}-{self.cfg.gpu_port}.proxy.runpod.net'

    async def ready(self, pod_id):
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            try:
                r = await client.get(self.url(pod_id) + '/ready')
                return r.status_code == 200 and r.json().get('ready') is True
            except (httpx.HTTPError, ValueError, TypeError):
                return False


class MockPod(RunPod):
    """Fully offline control-plane demonstration; not real speech/GPU."""
    def __init__(self, cfg):
        super().__init__(cfg)
        self.pods = {}
    async def create(self, name, env):
        pod = 'mock-' + secrets.token_hex(6)
        self.pods[pod] = {'id': pod, 'name': name, 'status': 'RUNNING'}
        return pod
    async def find_named(self, name):
        return next((p['id'] for p in self.pods.values() if p['name'] == name), None)
    async def state(self, pod_id):
        return self.pods[pod_id]
    async def terminate(self, pod_id):
        self.pods.pop(pod_id, None)
    async def ready(self, pod_id):
        return pod_id in self.pods
    def url(self, pod_id):
        raise ValueError('Mock provider never serves the live AI application')


async def expiring_chunks(chunks, deadline, clock=time.time):
    """Stop an HTTP response stream when its already-accepted lease expires."""
    try:
        async with asyncio.timeout(max(0, deadline - clock())):
            async for chunk in chunks:
                if clock() >= deadline:
                    break
                yield chunk
    except TimeoutError:
        return


class Gateway:
    def __init__(self, cfg: Config, provider=None, clock=time.time):
        self.cfg = cfg
        self.db = Database(cfg.db_path)
        self.provider = provider or (RunPod(cfg) if cfg.mode == 'runpod' else MockPod(cfg) if cfg.mode == 'mock' else None)
        self.clock = clock
        self.lock = asyncio.Lock()
        self.guardian = None
        self.pending = set()
        self.last_purge = 0.0

    def sign(self, value):
        mac = hmac.digest(self.cfg.key.encode(), value.encode(), 'sha256').hex()
        return value + '.' + mac

    def identify(self, token):
        try:
            value, signature = token.split('.', 1)
            if not re.fullmatch('[A-Za-z0-9_-]{32,128}', value):
                raise ValueError()
            expected = hmac.digest(self.cfg.key.encode(), value.encode(), 'sha256').hex()
            if not hmac.compare_digest(expected, signature):
                raise ValueError()
            return hashlib.sha256(value.encode()).hexdigest()
        except (TypeError, ValueError, AttributeError):
            return None

    def secret(self, lease_id, purpose):
        return hmac.digest(self.cfg.key.encode(),
                           ('portfolio:' + lease_id + ':' + purpose).encode(), 'sha256').hex()

    def ip(self, conn):
        ip = conn.client.host if conn.client else 'unknown'
        if ip in self.cfg.trusted_proxies:
            forwarded = conn.headers.get('x-forwarded-for', '')
            # Choose the closest untrusted hop, not a spoofable leftmost value.
            for candidate in reversed(forwarded.split(',')):
                candidate = candidate.strip()
                try:
                    normalized = str(ipaddress.ip_address(candidate))
                except ValueError:
                    continue
                if normalized not in self.cfg.trusted_proxies:
                    ip = normalized
                    break
        try:
            return str(ipaddress.ip_address(ip))
        except ValueError:
            return 'unknown'

    def log(self, req, event):
        ref = urlparse(req.headers.get('referer', '')).hostname or ''
        ua = ''.join(c for c in req.headers.get('user-agent', '') if c.isprintable())[:200]
        self.db.events(self.ip(req), ua, ref, event, self.cfg.retention_days)

    def current(self, owner):
        with self.db.tx() as db:
            own = db.execute('SELECT * FROM leases WHERE owner=? ORDER BY created DESC LIMIT 1',
                             (owner,)).fetchone()
            active = db.execute("SELECT * FROM leases WHERE status IN ('starting','running','stopping') "
                                'ORDER BY created LIMIT 1').fetchone()
        return (dict(own) if own else None, dict(active) if active else None)

    def _set(self, ident, **fields):
        if not fields:
            return
        names = list(fields)
        with self.db.tx() as db:
            db.execute('UPDATE leases SET ' + ','.join(k + '=?' for k in names) + ',updated=? WHERE id=?',
                       [fields[k] for k in names] + [self.clock(), ident])

    def _view(self, row, own=True):
        if not row:
            return {'status': 'idle', 'seconds_left': 0, 'launch_enabled': self.provider is not None}
        remaining = max(0, int(row['expires'] - self.clock()))
        if row['status'] == 'stopping' or (not remaining and row['status'] in ACTIVE):
            status = 'expired'
        else:
            status = row['status']
        return {'status': status, 'seconds_left': remaining,
                'launch_enabled': self.provider is not None,
                'live': own and status == 'running' and self.cfg.mode == 'runpod',
                'note': 'GPU is warming up' if status == 'starting' else ''}

    def status(self, owner):
        own, active = self.current(owner)
        if active and active['owner'] != owner:
            return {'status': 'busy', 'seconds_left': max(0, int(active['expires'] - self.clock())),
                    'launch_enabled': False}
        return self._view(own)

    async def start(self, owner, ip):
        if not self.provider:
            raise HTTPException(503, 'Live GPU is not configured yet')
        async with self.lock:
            now = self.clock()
            with self.db.tx() as db:
                existing = db.execute("SELECT * FROM leases WHERE status IN ('starting','running','stopping') "
                                      'ORDER BY created LIMIT 1').fetchone()
                if existing:
                    if existing['owner'] == owner and existing['expires'] > now:
                        return self._view(dict(existing))
                    raise HTTPException(409, 'Demo is occupied or shutting down')
                since = now - now % 86400
                if db.execute('SELECT count(*) FROM leases WHERE created>=?', (since,)).fetchone()[0] >= self.cfg.daily_limit:
                    raise HTTPException(429, 'Daily GPU demo budget reached')
                if db.execute('SELECT count(*) FROM leases WHERE created>=? AND ip=?',
                              (since, ip)).fetchone()[0] >= self.cfg.per_ip_limit:
                    raise HTTPException(429, 'Per-visitor daily GPU limit reached')
                lease = secrets.token_hex(10)
                db.execute('''INSERT INTO leases(id,owner,ip,status,created,expires,updated)
                              VALUES(?,?,?,'starting',?,?,?)''',
                           (lease, owner, ip, now, now + MAX_SECONDS, now))
            job = asyncio.create_task(self._provision(lease), name='gpu-start-' + lease)
            self.pending.add(job)
            job.add_done_callback(self.pending.discard)
            return {'status': 'starting', 'seconds_left': MAX_SECONDS, 'launch_enabled': True}

    async def _provision(self, ident):
        name = 'rizzler-portfolio-' + ident
        with self.db.tx() as db:
            lease = db.execute('SELECT expires FROM leases WHERE id=?', (ident,)).fetchone()
        if not lease:
            return
        try:
            if self.cfg.mode == 'runpod':
                env = {
                    'GEMINI_API_KEY': self.cfg.gemini_key,
                    'RIZZLER_DEPLOYMENT_MODE': 'demo',
                    'RIZZLER_ACCESS_KEY': self.secret(ident, 'voice'),
                    'RIZZLER_WORK_SIGNING_KEY': self.secret(ident, 'work'),
                    'RIZZLER_WORK_ROOT': '/tmp/rizzler-work',
                    'RIZZLER_ASR_DEVICE': 'cuda',
                    'RIZZLER_HOST': '0.0.0.0',
                    'RIZZLER_PORT': str(self.cfg.gpu_port),
                    'RIZZLER_STACK_DEADLINE': str(int(lease['expires'])),
                }
            else:
                env = {}
            pod_id = await self.provider.create(name, env)
            with self.db.tx() as db:
                row = db.execute('SELECT status,expires FROM leases WHERE id=?', (ident,)).fetchone()
                if row and row['status'] == 'starting':
                    db.execute('UPDATE leases SET pod_id=?,updated=? WHERE id=?',
                               (pod_id, self.clock(), ident))
                else:
                    # Lease expired or cancelled while cloud provisioning.
                    asyncio.create_task(self.provider.terminate(pod_id))
        except httpx.HTTPStatusError as exc:
            # Explicit 4xx validation/auth failures cannot become a healthy Pod.
            # A 429/5xx may have an uncertain outcome: reconcile by name first.
            if 400 <= exc.response.status_code < 500 and exc.response.status_code != 429:
                self._set(ident, status='failed', last_error='provider_rejected')
            else:
                self._set(ident, last_error='provisioning_uncertain')
        except Exception:
            # After a timeout or network cut, the remote create may have succeeded.
            # Never issue a duplicate create: reconcile the deterministic name.
            self._set(ident, last_error='provisioning_uncertain')

    async def tick(self):
        now = self.clock()
        if now - self.last_purge > 3600:
            with self.db.tx() as db:
                db.execute('DELETE FROM visit_events WHERE ts<?',
                           (now - self.cfg.retention_days * 86400,))
            self.last_purge = now
        if not self.provider:
            return
        with self.db.tx() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT * FROM leases WHERE status IN ('starting','running','stopping')")]
        for row in rows:
            ident, pod = row['id'], row['pod_id']
            no_pod_confirmed = False
            if not pod and row['status'] in ('starting', 'stopping'):
                try:
                    found = await self.provider.find_named('rizzler-portfolio-' + ident)
                    if found:
                        pod = found
                        self._set(ident, pod_id=pod)
                    else:
                        no_pod_confirmed = True
                except Exception:
                    continue
            if (not pod and no_pod_confirmed and row['last_error'] == 'provisioning_uncertain'
                    and now - row['created'] > 180 and now < row['expires']):
                self._set(ident, status='stopping', expires=now,
                          last_error='startup_unavailable')
                continue
            if now >= row['expires']:
                self._set(ident, status='stopping')
                if pod:
                    try:
                        await self.provider.terminate(pod)
                        self._set(ident, status='ended', pod_id='', last_error='')
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code == 404:
                            self._set(ident, status='ended', pod_id='', last_error='')
                        else:
                            self._set(ident, stop_attempts=row['stop_attempts'] + 1,
                                      last_error='shutdown_pending')
                    except Exception:
                        self._set(ident, stop_attempts=row['stop_attempts'] + 1,
                                  last_error='shutdown_pending')
                elif no_pod_confirmed and now - row['expires'] > 180:
                    # A provider LIST after expiry reports no matching pod.
                    # The operator should still retain account-level cost alerts.
                    self._set(ident, status='ended', pod_id='', last_error='')
                elif now - row['expires'] > 120:
                    self._set(ident, status='stopping', last_error='provisioning_uncertain')
                continue
            if not pod:
                continue
            if row['status'] in ('starting', 'running'):
                try:
                    state = await self.provider.state(pod)
                    if state.get('status') in ('ERROR', 'TERMINATED', 'EXITED'):
                        self._set(ident, status='stopping', expires=now,
                                  last_error='upstream_exited')
                    elif row['status'] == 'starting' and state.get('status') == 'RUNNING' and await self.provider.ready(pod):
                        self._set(ident, status='running')
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        self._set(ident, status='stopping', expires=now,
                                  last_error='upstream_missing')
                except Exception:
                    continue

    async def watchdog(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Provider/network outages are handled by retry; never expose details.
                pass
            await asyncio.sleep(5)

    async def begin(self):
        if self.provider:
            self.guardian = asyncio.create_task(self.watchdog(), name='gpu-lease-guardian')

    async def close(self):
        if self.guardian:
            self.guardian.cancel()
            await asyncio.gather(self.guardian, return_exceptions=True)
        # An interrupted provisioning request may have created a Pod.
        # On restart, reconciliation discovers it by its deterministic name.
        for task in list(self.pending):
            if not task.done():
                task.cancel()
        if self.pending:
            await asyncio.gather(*self.pending, return_exceptions=True)

    def authorized(self, owner):
        row, _ = self.current(owner)
        if (not row or row['status'] != 'running' or
                row['expires'] <= self.clock() or not POD_ID.fullmatch(row['pod_id'])):
            raise HTTPException(410, 'Demo expired or not ready')
        if self.cfg.mode != 'runpod':
            raise HTTPException(503, 'Mock GPU never hosts a real application')
        return row


def create_app(config: Config | None = None, provider=None, clock=time.time):
    cfg = config or Config.env()
    gateway = Gateway(cfg, provider=provider, clock=clock)

    @asynccontextmanager
    async def lifecycle(app):
        await gateway.begin()
        yield
        await gateway.close()

    app = FastAPI(lifespan=lifecycle, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.gateway = gateway

    def identity(req):
        return gateway.identify(req.cookies.get(COOKIE))

    def reject_origin(req):
        if req.headers.get('origin', '') != cfg.origin:
            raise HTTPException(403, 'Request origin not trusted')

    @app.middleware('http')
    async def headers(req: Request, call_next):
        try:
            response = await call_next(req)
        except Exception:
            # Framework handles the corresponding sanitized response.
            raise
        response.headers.update({
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'SAMEORIGIN',
            'Permissions-Policy': 'camera=(), geolocation=(), microphone=(self)',
            'Cache-Control': 'no-store',
            'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' wss:; "
                "font-src 'self'; frame-src 'self'; base-uri 'none'; object-src 'none'; "
                "form-action 'self'; frame-ancestors 'self'",
        })
        if cfg.origin.startswith('https://'):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    @app.get('/', response_class=HTMLResponse)
    async def home(req: Request):
        session = req.cookies.get(COOKIE)
        if not gateway.identify(session):
            session = gateway.sign(secrets.token_urlsafe(32))
        gateway.log(req, 'view')
        if not SITE.exists():
            raise HTTPException(503, 'Portfolio template missing')
        content = SITE.read_text(encoding='utf-8')
        # The public story deliberately omits model IDs, provider details and secrets.
        content = content.replace('__COLAB_NOTEBOOK_URL__', html.escape(cfg.colab_url or '#demo', quote=True))
        response = HTMLResponse(content)
        response.set_cookie(COOKIE, session, max_age=2*86400, httponly=True,
                            secure=cfg.origin.startswith('https://'), samesite='lax', path='/')
        return response

    @app.get('/stack_site.js')
    async def site_script():
        if not SITE_JS.is_file():
            raise HTTPException(503, 'Portfolio script unavailable')
        return Response(SITE_JS.read_text(encoding='utf-8'), media_type='text/javascript')

    @app.get('/api/status')
    async def status(req: Request):
        owner = identity(req)
        if not owner:
            return {'status': 'idle', 'seconds_left': 0, 'launch_enabled': False}
        return gateway.status(owner)

    @app.post('/api/start')
    async def start(req: Request):
        reject_origin(req)
        if req.headers.get('x-rizzler-action') != 'start':
            raise HTTPException(403, 'Explicit demo launch required')
        owner = identity(req)
        if not owner:
            raise HTTPException(401, 'Open portfolio landing first')
        result = await gateway.start(owner, gateway.ip(req))
        gateway.log(req, 'launch')
        return JSONResponse(result, status_code=202)

    @app.get('/api/health')
    async def health():
        return {'gateway': 'ready'}

    allowed = ('/api/', '/static/', '/work')
    request_header_names = {'content-type', 'accept', 'range', 'x-session-id',
                            'x-file-name', 'idempotency-key', 'x-csrf-token'}
    response_header_names = {'content-type', 'content-disposition', 'content-length',
                             'content-encoding', 'accept-ranges', 'content-range', 'etag'}

    async def proxy(req, path: str):
        owner = identity(req)
        if not owner:
            raise HTTPException(401, 'Demo session required')
        if req.method not in ('GET', 'HEAD', 'POST'):
            raise HTTPException(405, 'Unsupported demo operation')
        if req.method == 'POST':
            reject_origin(req)
        row = gateway.authorized(owner)
        upstream = gateway.provider.url(row['pod_id'])
        if path != '/' and not path.startswith(allowed):
            raise HTTPException(404, 'Not a permitted demo route')
        headers_to_send = {k: v for k, v in req.headers.items() if k.lower() in request_header_names}
        if path.startswith('/api/work/'):
            # This short-lived, owner-scoped bearer is never returned to the browser.
            import base64
            owner_name = 'guest_' + row['id']
            payload = {'aud': 'rizzler-work-v1', 'sub': owner_name,
                       'exp': int(min(gateway.clock() + 300, row['expires']))}
            packed = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True,
                separators=(',', ':')).encode()).rstrip(b'=').decode()
            sig = base64.urlsafe_b64encode(hmac.digest(gateway.secret(row['id'], 'work').encode(),
                    packed.encode(), 'sha256')).rstrip(b'=').decode()
            headers_to_send['Authorization'] = 'Bearer ' + packed + '.' + sig
        if path.startswith('/api/'):
            headers_to_send['x-rizzler-key'] = gateway.secret(row['id'], 'voice')
        url = upstream + path
        if req.url.query:
            url += '?' + req.url.query[:1000]
        incoming = bytearray()
        async for chunk in req.stream():
            incoming.extend(chunk)
            if len(incoming) > 9_000_000:
                raise HTTPException(413, 'Demo request too large')
        client = httpx.AsyncClient(timeout=httpx.Timeout(20, read=120), follow_redirects=False)
        try:
            outbound = client.build_request(req.method, url, headers=headers_to_send, content=incoming)
            remote = await client.send(outbound, stream=True)
        except httpx.HTTPError:
            await client.aclose()
            raise HTTPException(502, 'GPU application temporarily unreachable') from None
        # Do not leak provider coordinates, internal cookies, CORS or remote redirects.
        allowed_responses = {k: v for k, v in remote.headers.items() if k.lower() in response_header_names}
        if remote.status_code in (301, 302, 303, 307, 308):
            allowed_responses.pop('location', None)
            await remote.aclose()
            await client.aclose()
            raise HTTPException(502, 'Unexpected upstream redirect')
        if remote.headers.get('content-type', '').startswith('text/html'):
            # HTML rewrite is limited to demo usability, never secrets or credentials.
            body = await remote.aread()
            await remote.aclose(); await client.aclose()
            if len(body) > 2_000_000:
                raise HTTPException(502, 'Unexpected large application page')
            html = body.decode('utf-8', errors='replace')
            html = html.replace('placeholder="Private server key"',
                                'value="' + DEMO_DUMMY + '" placeholder="Demo access configured"')
            html = html.replace('placeholder="Short-lived bearer token"',
                                'value="' + DEMO_DUMMY + '" placeholder="Access managed by gateway"')
            html = html.replace('Enter <code>RIZZLER_ACCESS_KEY</code>. This key stays in your browser memory and is not stored.',
                                'Your temporary portfolio demo access is configured. Press Connect to allow your microphone.')
            return HTMLResponse(html, status_code=remote.status_code)
        return StreamingResponse(expiring_chunks(remote.aiter_raw(),
                                 row['expires'], gateway.clock), status_code=remote.status_code,
                                 headers=allowed_responses,
                                 background=BackgroundTask(_close_remote, remote, client))

    @app.api_route('/live/', methods=['GET', 'HEAD'])
    async def live(req: Request):
        return await proxy(req, '/')

    @app.api_route('/work', methods=['GET', 'HEAD'])
    async def work(req: Request):
        return await proxy(req, '/work')

    @app.api_route('/static/{path:path}', methods=['GET', 'HEAD'])
    async def static(req: Request, path: str):
        if not path or '..' in path.split('/'):
            raise HTTPException(404)
        return await proxy(req, '/static/' + path)

    @app.api_route('/api/{path:path}', methods=['GET', 'HEAD', 'POST'])
    async def api(req: Request, path: str):
        if path.startswith(('start', 'status', 'health')) or not path:
            raise HTTPException(404)
        return await proxy(req, '/api/' + path)

    @app.websocket('/ws')
    async def websocket_bridge(ws: WebSocket):
        if ws.headers.get('origin') != cfg.origin:
            await ws.close(code=1008)
            return
        owner = gateway.identify(ws.cookies.get(COOKIE))
        if not owner:
            await ws.close(code=1008)
            return
        try:
            row = gateway.authorized(owner)
        except HTTPException:
            await ws.close(code=1008)
            return
        try:
            import websockets
            address = gateway.provider.url(row['pod_id']).replace('https://', 'wss://', 1) + '/ws'
            async with websockets.connect(address, open_timeout=12, close_timeout=5,
                                          max_size=4_000_000) as remote:
                await ws.accept()
                async def forward_in():
                    first = True
                    while gateway.clock() < row['expires']:
                        frame = await ws.receive()
                        if frame['type'] == 'websocket.disconnect':
                            return
                        if frame.get('text') is not None:
                            payload = frame['text']
                            if first:
                                auth_frame = json.loads(payload)
                                if not isinstance(auth_frame, dict) or auth_frame.get('type') != 'auth':
                                    return
                                auth_frame['token'] = gateway.secret(row['id'], 'voice')
                                payload = json.dumps(auth_frame, separators=(',', ':'))
                                first = False
                            await remote.send(payload)
                        elif frame.get('bytes') is not None:
                            if first:
                                return
                            await remote.send(frame['bytes'])
                async def forward_out():
                    async for frame in remote:
                        if gateway.clock() >= row['expires']:
                            return
                        if isinstance(frame, str):
                            await ws.send_text(frame)
                        else:
                            await ws.send_bytes(frame)
                tasks = [asyncio.create_task(forward_in()), asyncio.create_task(forward_out())]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED,
                                                   timeout=max(0, row['expires'] - gateway.clock()))
                for task in pending:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except (WebSocketDisconnect, Exception):
            pass
        finally:
            try:
                await ws.close(code=1000)
            except RuntimeError:
                pass

    return app


async def _close_remote(remote, client):
    await remote.aclose()
    await client.aclose()


def report_visitors(cfg: Config, show_ip: bool = False):
    db = Database(cfg.db_path)
    since = time.time() - cfg.retention_days * 86400
    with db.tx() as conn:
        rows = conn.execute('''SELECT datetime(ts,'unixepoch') time, ip, ua, referrer_host, event
                               FROM visit_events WHERE ts>=? ORDER BY ts DESC LIMIT 200''', (since,)).fetchall()
        counts = conn.execute('SELECT event, count(*) FROM visit_events WHERE ts>=? GROUP BY event',
                              (since,)).fetchall()
    print('Event counts:', dict(counts))
    for row in rows:
        ip = row['ip'] if show_ip else '[redacted]'
        print(row['time'], row['event'], ip, row['ua'][:80], row['referrer_host'])


def main():
    p = argparse.ArgumentParser(description='Rizzler portfolio demo gateway')
    p.add_argument('command', nargs='?', choices=('serve', 'visitors'), default='serve')
    p.add_argument('--show-ip', action='store_true', help='Show logged IPs locally (operator only)')
    args = p.parse_args()
    cfg = Config.env()
    if args.command == 'visitors':
        report_visitors(cfg, show_ip=args.show_ip)
    else:
        import uvicorn
        print('Rizzler portfolio at', cfg.origin)
        print('Provider mode:', cfg.mode, '| automatic trial length:', MAX_SECONDS//60, 'minutes')
        uvicorn.run(create_app(cfg), host=cfg.listen_host, port=cfg.listen_port,
                    proxy_headers=False, access_log=False, workers=1)


if __name__ == '__main__':
    main()
