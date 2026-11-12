"""Offline tests: no GPU is started and no third-party API is contacted."""
import asyncio
import secrets
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stack import Config, Gateway, MockPod, create_app, MAX_SECONDS


@pytest.fixture
def setup(tmp_path):
    now = [1_800_000_000.0]
    cfg = Config(origin='http://testserver', key='a' * 64, db_path=tmp_path / 'sessions.sqlite3',
                 mode='mock', daily_limit=3, per_ip_limit=2)
    provider = MockPod(cfg)
    app = create_app(cfg, provider=provider, clock=lambda: now[0])
    with TestClient(app, base_url='http://testserver') as client:
        yield client, app.state.gateway, provider, now


def launch(client):
    return client.post('/api/start', headers={'origin': 'http://testserver', 'x-rizzler-action': 'start'})


def tick(client, gate):
    return client.portal.call(gate.tick)


def test_landing_never_starts_gpu_and_privacy_notice(setup):
    client, gate, provider, _ = setup
    assert client.get('/api/status').json()['status'] == 'idle'
    page = client.get('/')
    assert page.status_code == 200
    assert 'MAC' in page.text
    assert 'verified outcomes' in page.text or 'Verified' in page.text
    assert 'rizzler_demo_visit=' in page.headers['set-cookie']
    assert 'HttpOnly' in page.headers['set-cookie']
    assert client.get('/stack_site.js').status_code == 200
    assert not provider.pods
    assert client.get('/api/status').json()['status'] == 'idle'


def test_explicit_start_and_restart_after_expiry(setup):
    client, gate, provider, now = setup
    client.get('/')
    assert client.post('/api/start').status_code == 403  # no origin / real user gesture
    assert client.post('/api/start', headers={'origin':'http://testserver'}).status_code == 403
    response = launch(client)
    assert response.status_code == 202, response.text
    assert response.json()['status'] == 'starting'
    client.portal.call(asyncio.sleep, .01)
    tick(client, gate)
    state = client.get('/api/status').json()
    assert state['status'] == 'running'
    assert state['seconds_left'] == MAX_SECONDS
    assert len(provider.pods) == 1
    assert launch(client).json()['status'] == 'running'  # idempotent owner retries
    now[0] += MAX_SECONDS + 1
    assert client.get('/api/status').json()['status'] == 'expired'
    assert client.get('/live/').status_code == 410
    tick(client, gate)
    assert client.get('/api/status').json()['status'] == 'ended'
    assert not provider.pods
    later = launch(client)
    assert later.status_code == 202
    client.portal.call(asyncio.sleep, .01)
    tick(client, gate)
    assert len(provider.pods) == 1
    assert client.get('/api/status').json()['status'] == 'running'
    assert launch(client).status_code == 202


def test_separate_visitor_cannot_hijack_active_demo(setup):
    client, gate, provider, now = setup
    client.get('/')
    assert launch(client).status_code == 202
    client.portal.call(asyncio.sleep, .01)
    tick(client, gate)
    original = client.cookies.get('rizzler_demo_visit')
    client.cookies.clear()
    client.get('/')
    assert client.cookies.get('rizzler_demo_visit') != original
    assert client.get('/api/status').json()['status'] == 'busy'
    assert launch(client).status_code == 409
    assert client.get('/work').status_code == 410
    assert len(provider.pods) == 1


def test_daily_and_per_ip_budget(setup):
    client, gate, provider, now = setup
    client.get('/')
    for i in range(2):
        assert launch(client).status_code == 202
        client.portal.call(asyncio.sleep, .01)
        tick(client, gate)
        now[0] += MAX_SECONDS + 1
        tick(client, gate)
    assert launch(client).status_code == 429
    assert not provider.pods


def test_recovery_reattaches_pod_by_deterministic_name(setup):
    client, gate, provider, now = setup
    client.get('/')
    assert launch(client).status_code == 202
    client.portal.call(asyncio.sleep, .01)
    tick(client, gate)
    with gate.db.tx() as db:
        row = db.execute('SELECT id FROM leases ORDER BY created DESC LIMIT 1').fetchone()
        db.execute("UPDATE leases SET pod_id='',status='starting' WHERE id=?", (row['id'],))
    tick(client, gate)
    assert client.get('/api/status').json()['status'] == 'running'
    assert len(provider.pods) == 1


def test_provider_shutdown_retry_and_expired_gateway_blocks(setup):
    client, gate, provider, now = setup
    client.get('/')
    launch(client)
    client.portal.call(asyncio.sleep, .01)
    tick(client, gate)
    actual = provider.terminate
    calls = [0]
    async def flaky(pod_id):
        calls[0] += 1
        if calls[0] == 1:
            raise OSError('Provider temporarily offline')
        return await actual(pod_id)
    provider.terminate = flaky
    now[0] += 1801
    tick(client, gate)
    assert client.get('/api/status').json()['status'] == 'expired'
    assert len(provider.pods) == 1
    assert launch(client).status_code == 409
    tick(client, gate)
    assert client.get('/api/status').json()['status'] == 'ended'
    assert len(provider.pods) == 0


def test_sessions_tamper_protection_and_privacy_retention(setup):
    client, gate, provider, now = setup
    client.get('/', headers={'user-agent': 'portfolio-test', 'referer': 'https://example.org/something'})
    original = client.cookies.get('rizzler_demo_visit')
    client.cookies.set('rizzler_demo_visit', original[:-1] + ('0' if original[-1] != '0' else '1'))
    assert client.get('/api/status').json()['launch_enabled'] is False
    assert launch(client).status_code == 401
    client.cookies.clear()
    client.get('/')
    with gate.db.tx() as db:
        logs = db.execute('SELECT ip,ua,referrer_host,event FROM visit_events').fetchall()
    assert logs[0]['ua'] == 'portfolio-test'
    assert logs[0]['referrer_host'] == 'example.org'
    assert logs[0]['event'] == 'view'


def test_mock_mode_never_releases_real_demo_endpoint(setup):
    client, gate, provider, now = setup
    client.get('/')
    launch(client)
    client.portal.call(asyncio.sleep, .01)
    tick(client, gate)
    assert client.get('/api/status').json()['live'] is False
    assert client.get('/live/').status_code == 503


def test_config_fails_closed_when_unconfigured(tmp_path):
    with pytest.raises(ValueError):
        Config(origin='http://public-example.test', key='a'*64, db_path=tmp_path/'x')
    with pytest.raises(ValueError):
        Config(origin='https://example.org', key='a'*64, mode='runpod', db_path=tmp_path/'x')
    with pytest.raises(ValueError):
        Config(origin='https://example.org', key='short', db_path=tmp_path/'x')
