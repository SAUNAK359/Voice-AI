"""Phase-0 app contract tests: no GPU, network or real secrets required."""
from __future__ import annotations
# Legacy source CI intentionally installs --no-deps; the separate app CI installs
# [test] and executes all integration tests. Explicitly skip only in the
# dependency-free legacy test matrix, rather than import-failing discovery.
import importlib.util
import unittest
if any(importlib.util.find_spec(pkg) is None for pkg in ("numpy", "pytest", "fastapi", "httpx")):
    raise unittest.SkipTest("App integration dependencies unavailable; covered by Rizzler App CI")
import asyncio
import base64
import secrets
import struct
from threading import Event
import numpy as np
import pytest
from fastapi.testclient import TestClient

from rizzler.api import create_app
from rizzler.audio import pcm16_to_mono, to_pcm16
from rizzler.config import Settings
from rizzler.providers import GeminiLLM
from rizzler.sessions import Sessions
from rizzler.voice import VoiceEngine, ProviderSet, phrases

KEY = 'test-application-private-key-12345'
SESSION = 'session_unit_test'


class FakeASR:
    def transcribe(self, audio):
        assert audio.dtype == np.float32 and len(audio) > 2000
        return 'Please explain the result'


class FakeLLM:
    async def stream(self, text, history):
        assert text == 'Please explain the result'
        yield 'This is a verified test sentence. '
        await asyncio.sleep(0)
        yield 'Another short sentence completes the answer.'


class FakeTTS:
    def synthesize(self, text):
        assert text.strip()
        return (np.full(2400, 0.05, dtype='<f4') * 32767).astype('<i2').tobytes()


class EmptyASR(FakeASR):
    def transcribe(self, audio):
        return ''


class BrokenTTS(FakeTTS):
    def synthesize(self, text):
        raise RuntimeError('private prompt / internal value must not reach browser')


@pytest.fixture
def cfg():
    return Settings(access_key=KEY)


@pytest.fixture
def client(cfg):
    with TestClient(create_app(cfg, ProviderSet(FakeASR(), FakeLLM(), FakeTTS()))) as c:
        yield c


def body(rate=16000, seconds=1):
    return (np.ones(rate * seconds, dtype=np.float32) * .1 * 32767).astype('<i2').tobytes()


def headers(sid=SESSION):
    return {'x-rizzler-key': KEY, 'x-session-id': sid, 'x-sample-rate': '16000'}


def test_app_boot_and_static(client):
    assert client.get('/health').status_code == 200
    assert client.get('/health').json()['model_initialized']['asr'] is False
    assert client.get('/').status_code == 200
    assert 'Rizzler' in client.get('/').text
    assert client.get('/static/app.js').status_code == 200
    assert "unsafe-inline" not in client.get('/').headers['content-security-policy']


def test_no_access_key_rejected(client):
    assert client.post('/api/auth').status_code == 401
    assert client.post('/api/turn', content=body()).status_code == 401
    assert client.post('/api/interrupt').status_code == 401
    assert client.post('/api/reset').status_code == 401


def test_authorized_auth(client):
    assert client.post('/api/auth', headers={'x-rizzler-key': KEY}).json()['ok']


def test_full_http_turn(client):
    response = client.post('/api/turn', headers=headers(), content=body())
    assert response.status_code == 200, response.text
    output = response.json()
    assert output['transcript'] == 'Please explain the result'
    assert 'Another short sentence' in output['answer']
    assert len(base64.b64decode(output['audio_b64'])) > 200
    assert output['sample_rate'] == 24000
    assert output['metrics']['outcome'] == 'ok'
    assert output['metrics']['measurement'].endswith('not_browser_audible')


def test_http_session_context_and_reset(client):
    response = client.post('/api/turn', headers=headers(), content=body())
    assert response.status_code == 200
    store = client.app.state.sessions.sessions
    assert len(store[SESSION].history) == 2
    assert client.post('/api/reset', headers=headers()).status_code == 200
    assert store[SESSION].history == []


def test_http_session_isolation(client):
    assert client.post('/api/turn', headers=headers('session_A'), content=body()).status_code == 200
    assert client.post('/api/turn', headers=headers('session_B'), content=body()).status_code == 200
    store = client.app.state.sessions.sessions
    assert len(store['session_A'].history) == 2
    assert len(store['session_B'].history) == 2
    assert client.post('/api/reset', headers=headers('session_A')).status_code == 200
    assert len(store['session_B'].history) == 2
    assert client.post('/api/interrupt', headers=headers('session_B')).json() == {'cancelled': False}


def test_invalid_session_id(client):
    assert client.post('/api/turn', headers=headers('../../bad'), content=body()).status_code == 400


def test_invalid_rate(client):
    h = headers()
    h['x-sample-rate'] = 'not_a_number'
    assert client.post('/api/turn', headers=h, content=body()).status_code == 400


def test_oversized_audio(client):
    assert client.post('/api/turn', headers=headers(), content=body(seconds=24)).status_code == 413


def test_invalid_pcm(client):
    assert client.post('/api/turn', headers=headers(), content=b'odd').status_code == 502


def test_empty_transcript_is_not_success(cfg):
    with TestClient(create_app(cfg, ProviderSet(EmptyASR(), FakeLLM(), FakeTTS()))) as c:
        assert c.post('/api/turn', headers=headers(), content=body()).status_code == 502


def test_tts_failure_does_not_leak_private_details(cfg):
    with TestClient(create_app(cfg, ProviderSet(FakeASR(), FakeLLM(), BrokenTTS()))) as c:
        r = c.post('/api/turn', headers=headers(), content=body())
        assert r.status_code == 502
        assert 'private prompt' not in r.text


def test_websocket_origin_rejected(client):
    with pytest.raises(Exception):
        with client.websocket_connect('/ws', headers={'origin': 'https://evil.example'}) as ws:
            ws.receive_json()


def test_websocket_bad_key_rejected(client):
    with pytest.raises(Exception):
        with client.websocket_connect('/ws', headers={'origin': 'http://testserver'}) as ws:
            ws.send_json({'type': 'auth', 'token': 'invalid', 'client_id': 'aaa', 'sample_rate': 16000})
            ws.receive_json()


def test_websocket_full_turn(client):
    with client.websocket_connect('/ws', headers={'origin': 'http://testserver'}) as ws:
        ws.send_json({'type': 'auth', 'token': KEY, 'client_id': 'web_test', 'sample_rate': 16000})
        assert ws.receive_json()['type'] == 'ready'
        ws.send_json({'type': 'speech_start', 'generation': 1})
        assert ws.receive_json()['type'] == 'status'
        for i in range(0, len(body()), 8000):
            ws.send_bytes(body()[i:i+8000])
        ws.send_json({'type': 'speech_end', 'generation': 1})
        events = []
        for _ in range(30):
            m = ws.receive()
            if m.get('bytes') is not None:
                assert struct.unpack('<I', m['bytes'][:4])[0] == 1
                events.append('audio')
            else:
                obj = __import__('json').loads(m['text'])
                events.append(obj['type'])
                if obj['type'] == 'done':
                    break
        assert 'transcript' in events and 'assistant_text' in events
        assert 'audio' in events and events[-1] == 'done'


def test_audio_conversions():
    audio = pcm16_to_mono(body(), 16000)
    assert audio.dtype == np.float32 and len(audio) == 16000
    audio48 = pcm16_to_mono(body(48000), 48000)
    assert len(audio48) == 16000
    pcm = to_pcm16(np.ones(2400, dtype=np.float32))
    assert len(pcm) == 4800
    with pytest.raises(ValueError):
        to_pcm16([float('nan')])


def test_phrases_split():
    x, tail = phrases('This is a complete sentence. This is a longer second sentence.')
    assert x[0] == 'This is a complete sentence.'
    rest, remain = phrases(tail, flush=True)
    assert len(x + rest) >= 2 and remain == ''


def test_settings_fail_closed():
    with pytest.raises(ValueError):
        Settings(access_key='short')
    with pytest.raises(ValueError):
        Settings(access_key=KEY, asr_device='rocm')


def test_session_capacity():
    x = Sessions(capacity=1)
    x.get('one')
    with pytest.raises(RuntimeError):
        x.get('two')



def test_ws_interruption_then_next_generation(client):
    # Regression: an interrupt must not consume the client's NEXT seq number.
    with client.websocket_connect('/ws', headers={'origin': 'http://testserver'}) as ws:
        ws.send_json({'type': 'auth', 'token': KEY, 'client_id': 'barge_test', 'sample_rate': 16000})
        assert ws.receive_json()['type'] == 'ready'
        ws.send_json({'type': 'speech_start', 'generation': 1})
        assert ws.receive_json()['generation'] == 1
        ws.send_json({'type': 'interrupt'})
        m = ws.receive_json()
        assert m['type'] == 'interrupted' and m['generation'] == 1
        ws.send_json({'type': 'speech_start', 'generation': 2})
        m = ws.receive_json()
        assert m['type'] == 'status' and m['generation'] == 2


def test_ws_new_conversation_then_next_generation(client):
    with client.websocket_connect('/ws', headers={'origin': 'http://testserver'}) as ws:
        ws.send_json({'type': 'auth', 'token': KEY, 'client_id': 'new_chat_test', 'sample_rate': 16000})
        assert ws.receive_json()['type'] == 'ready'
        ws.send_json({'type': 'speech_start', 'generation': 1})
        assert ws.receive_json()['type'] == 'status'
        ws.send_json({'type': 'new_conversation'})
        ws.send_json({'type': 'speech_start', 'generation': 2})
        assert ws.receive_json()['generation'] == 2
