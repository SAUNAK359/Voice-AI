"""Phase 5: external OIDC, cookie isolation, CSRF, recovery and scanner tests."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import tarfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

if any(importlib.util.find_spec(name) is None for name in
       ("pytest", "fastapi", "httpx", "jwt", "cryptography", "numpy")):
    raise unittest.SkipTest("Phase-5 extras are exercised in Rizzler App CI")

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from rizzler.api import create_app
from rizzler.backup import backup, restore
from rizzler.config import Settings
from rizzler.identity import Identity, OIDCSettings, SessionStore
from rizzler.operations import Operations
from rizzler.upload_scan import scan_clamd, ScanUnavailable
from rizzler.work_store import WorkStore

VOICE = "demo-key-unused-in-production-mode-123"
SIGNING = "independent-work-signing-value-1234567890"
SESSION = "independent-session-signing-value-1234567890"
OPS = "independent-operations-token-value-1234567890"
OWNER_A = "u_" + "a" * 40
OWNER_B = "u_" + "b" * 40
ORIGIN = "https://testserver"


def oidc_settings():
    return OIDCSettings(
        issuer="https://id.example.test",
        authorize_url="https://id.example.test/authorize",
        token_url="https://id.example.test/token",
        jwks_url="https://id.example.test/jwks",
        client_id="test-client",
        redirect_uri=ORIGIN + "/auth/callback",
    )


@pytest.fixture
def prod(tmp_path, monkeypatch):
    values = {
        "RIZZLER_DEPLOYMENT_MODE": "production",
        "RIZZLER_WORK_ROOT": str(tmp_path / "durable"),
        "RIZZLER_WORK_SIGNING_KEY": SIGNING,
        "RIZZLER_SESSION_SIGNING_KEY": SESSION,
        "RIZZLER_OPERATIONS_TOKEN": OPS,
        "RIZZLER_CLAMD_HOST": "localhost",
        "RIZZLER_OIDC_ISSUER": "https://id.example.test",
        "RIZZLER_OIDC_AUTHORIZE_URL": "https://id.example.test/authorize",
        "RIZZLER_OIDC_TOKEN_URL": "https://id.example.test/token",
        "RIZZLER_OIDC_JWKS_URL": "https://id.example.test/jwks",
        "RIZZLER_OIDC_CLIENT_ID": "test-client",
        "RIZZLER_OIDC_REDIRECT_URI": ORIGIN + "/auth/callback",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    app = create_app(Settings(access_key=VOICE))
    with TestClient(app, base_url=ORIGIN) as client:
        yield client


def sign_in(client, who):
    token, csrf = client.app.state.identity.sessions.issue(who)
    client.cookies.set("rizzler_session", token)
    client.cookies.set("rizzler_csrf", csrf)
    return {"origin": ORIGIN, "x-csrf-token": csrf}


def test_startup_fail_closed_if_required_production_settings_absent(monkeypatch):
    monkeypatch.setenv("RIZZLER_DEPLOYMENT_MODE", "production")
    for key in ("RIZZLER_WORK_ROOT", "RIZZLER_WORK_SIGNING_KEY", "RIZZLER_OIDC_ISSUER"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError):
        create_app(Settings(access_key=VOICE))


def test_oidc_rejects_non_https_endpoints():
    from dataclasses import replace
    with pytest.raises(ValueError):
        replace(oidc_settings(), token_url="http://id.example.test/token")
    with pytest.raises(ValueError):
        replace(oidc_settings(), redirect_uri="https://rizzler.test/redirect")


def test_hash_stored_only_rotation_revokes_old_cookie(tmp_path):
    sessions = SessionStore(tmp_path)
    token, csrf = sessions.issue(OWNER_A, ttl=120)
    assert sessions.validate(token, csrf) == OWNER_A
    assert token not in sessions.path.read_bytes().decode("latin1", errors="ignore")
    second, second_csrf = sessions.rotate(token, csrf)
    with pytest.raises(PermissionError):
        sessions.validate(token)
    assert sessions.validate(second, second_csrf) == OWNER_A
    sessions.revoke(second)
    with pytest.raises(PermissionError):
        sessions.validate(second)


def test_only_one_concurrent_refresh_can_use_old_session(tmp_path):
    sessions = SessionStore(tmp_path)
    original, csrf = sessions.issue(OWNER_A)
    def rotate(_):
        try:
            return sessions.rotate(original, csrf)
        except PermissionError:
            return None
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(rotate, range(5)))
    assert sum(x is not None for x in results) == 1


def test_oidc_pkce_state_nonce_and_signature(monkeypatch, tmp_path):
    identity = Identity(oidc_settings(), tmp_path, SESSION)
    redirect = identity.login()
    query = parse_qs(urlparse(redirect.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert "code_verifier" not in query
    flow = redirect.raw_headers[-1][1].decode()
    # The only cookie set by login is the signed, HttpOnly flow cookie.
    from http.cookies import SimpleCookie
    cookies = SimpleCookie()
    for key, value in redirect.raw_headers:
        if key.lower() == b"set-cookie":
            cookies.load(value.decode())
    token = cookies["rizzler_oidc_flow"].value
    info = identity._verify_flow(token)
    assert info["state"] == query["state"][0]
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"], jwk["use"] = "test-key", "sig"
    claims = {"iss": oidc_settings().issuer, "aud": oidc_settings().client_id,
              "sub": "real-external-provider-user-42", "iat": int(time.time()),
              "exp": int(time.time()) + 300, "nonce": info["nonce"]}
    id_token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})

    class FakeResponse:
        def __init__(self, data):
            self.data = data
        def raise_for_status(self):
            return None
        def json(self):
            return self.data

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, url, data):
            assert data["code_verifier"] == info["verifier"]
            return FakeResponse({"id_token": id_token})
        async def get(self, url):
            return FakeResponse({"keys": [jwk]})

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    import asyncio
    issued, csrf = asyncio.run(identity.exchange("code-123", info["state"], token, None))
    result = identity.sessions.validate(issued, csrf)
    assert result.startswith("u_") and len(result) == 42
    with pytest.raises(PermissionError):
        asyncio.run(identity.exchange("code-123", "wrong-state", token, None))
    with pytest.raises(PermissionError):
        asyncio.run(identity.exchange("code-123", info["state"], token, "https://attacker.test"))


def test_production_shared_demo_key_cannot_access_private_work(prod):
    assert prod.get("/api/work/jobs", headers={"x-rizzler-key": VOICE}).status_code == 401
    assert prod.post("/api/auth", headers={"x-rizzler-key": VOICE}).status_code == 403
    assert prod.get("/ready").json() == {"ready": True, "mode": "production"}
    assert prod.get("/internal/metrics").status_code == 401
    assert prod.get("/internal/metrics", headers={"authorization": "Bearer " + OPS}).status_code == 200


def test_cookie_owner_scope_and_csrf(prod):
    headers = sign_in(prod, OWNER_A)
    assert prod.get("/auth/session").json()["subject"] == OWNER_A
    payload = {"objective": "Create a deterministic report for this user",
               "deliverables": ["md"], "uploads": []}
    assert prod.post("/api/work/jobs", json=payload, headers={"idempotency-key": "job_auth_001"}).status_code == 403
    assert prod.post("/api/work/jobs", json=payload,
                     headers={**headers, "idempotency-key": "job_auth_001",
                              "origin": "https://evil.example"}).status_code == 403
    created = prod.post("/api/work/jobs", json=payload,
                        headers={**headers, "idempotency-key": "job_auth_001"})
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]
    sign_in(prod, OWNER_B)
    assert prod.get(f"/api/work/jobs/{job_id}").status_code == 404
    assert prod.get(f"/api/work/jobs/{job_id}/events").status_code == 404
    assert prod.post(f"/api/work/jobs/{job_id}/cancel",
                     headers={"origin": ORIGIN, "x-csrf-token": prod.cookies.get("rizzler_csrf")}).status_code == 404


def test_voice_ws_authenticated_owner_not_client_chosen(prod):
    headers = sign_in(prod, OWNER_A)
    with prod.websocket_connect("/ws", headers={"origin": ORIGIN}) as ws:
        ws.send_json({"type": "auth", "token": "wrong-demo-secret",
                      "client_id": "attacker_selected_id", "sample_rate": 16000})
        assert ws.receive_json()["type"] == "ready"
        assert OWNER_A in prod.app.state.sessions.sessions
        assert "attacker_selected_id" not in prod.app.state.sessions.sessions


def test_refresh_logout_revocation_and_private_cookies(prod):
    headers = sign_in(prod, OWNER_A)
    old = prod.cookies.get("rizzler_session")
    resp = prod.post("/auth/refresh", headers=headers)
    assert resp.status_code == 200
    assert resp.cookies.get("rizzler_session") != old
    assert "httponly" in resp.headers["set-cookie"].lower()
    with pytest.raises(PermissionError):
        prod.app.state.identity.sessions.validate(old)
    # TestClient's manually inserted domainless cookie differs from a
    # browser's host-scoped Set-Cookie. Keep only the rotated response cookies.
    prod.cookies.clear()
    prod.cookies.update(resp.cookies)
    new_headers = {"origin": ORIGIN, "x-csrf-token": prod.cookies.get("rizzler_csrf")}
    assert prod.post("/auth/logout", headers=new_headers).status_code == 200
    assert prod.get("/auth/session").status_code == 401


def test_upload_scanner_fail_closed_and_no_file_published(prod):
    headers = sign_in(prod, OWNER_A)
    resp = prod.post("/api/work/uploads",
                     headers={**headers, "x-file-name": "numbers.csv"},
                     content=b"name,value\na,12\nb,34\n")
    assert resp.status_code == 503
    assert prod.app.state.work.list_jobs(OWNER_A) == []
    uploads = prod.app.state.work.root / "uploads" / OWNER_A
    assert not uploads.exists() or not list(uploads.iterdir())


def test_clamd_protocol_and_infected_fail_closed(monkeypatch):
    class Socket:
        def __init__(self, response):
            self.response = response
            self.bytes = bytearray()
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def settimeout(self, timeout):pass
        def sendall(self, data):self.bytes.extend(data)
        def recv(self, count):
            data,self.response = self.response,b""
            return data
    import rizzler.upload_scan as upload_scan
    good = Socket(b"stream: OK\x00")
    monkeypatch.setattr(upload_scan.socket,"create_connection", lambda *args, **kwargs: good)
    scan_clamd(b"safe", "scanner")
    assert good.bytes.startswith(b"zINSTREAM\x00")
    bad = Socket(b"stream: Eicar-Test-Signature FOUND\x00")
    monkeypatch.setattr(upload_scan.socket,"create_connection", lambda *args, **kwargs: bad)
    with pytest.raises(ScanUnavailable):
        scan_clamd(b"infected", "scanner")
    def unavailable(*args, **kwargs):
        raise OSError("scanner offline")
    monkeypatch.setattr(upload_scan.socket,"create_connection", unavailable)
    with pytest.raises(ScanUnavailable):
        scan_clamd(b"safe", "scanner")


def test_archive_defense_rejects_path_traversal_and_macros(tmp_path):
    store = WorkStore(tmp_path / "db")
    import zipfile
    for member in ("../evil", "xl/externalLinks/externalLink1.xml", "xl/vbaProject.bin"):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("xl/workbook.xml", "<workbook/>")
            archive.writestr(member, "bad")
        with pytest.raises(ValueError):
            store.register_upload(OWNER_A, "unsafe.xlsx", buffer.getvalue())


def test_backup_roundtrip_and_reject_corruption(tmp_path):
    root, restored = tmp_path / "work", tmp_path / "restored"
    store = WorkStore(root)
    SessionStore(root)
    store.submit(OWNER_A,"Create an example report",["md"],"backup_test_001",[])
    (root/"uploads"/OWNER_A).mkdir(parents=True)
    (root/"uploads"/OWNER_A/"sample.csv").write_bytes(b"a,b\n1,2\n")
    path = tmp_path / "backup.tar.gz"
    manifest = backup(root, path)
    assert "jobs.sqlite3" in [item["path"] for item in manifest["files"]]
    restore(path, restored)
    assert WorkStore(restored).list_jobs(OWNER_A)
    assert (restored/"uploads"/OWNER_A/"sample.csv").read_bytes() == b"a,b\n1,2\n"
    with pytest.raises(ValueError):
        restore(path, restored)


def test_operations_aggregate_does_not_record_sensitive_query_ids():
    metrics = Operations()
    metrics.record("GET","/api/work/jobs/{jid}",200,10)
    metrics.record("POST","/api/work/jobs/{jid}",403,30)
    report=metrics.snapshot()
    assert report["http_latency_ms"]["samples"]==2
    assert "secret_owner" not in json.dumps(report)
    assert all("{" not in row["route"] for row in report["requests_by_route_class"])
