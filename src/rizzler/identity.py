"""OIDC authorization-code + PKCE, server-owned revocable sessions.

No password storage or public token-mint endpoint. The trusted provider must
supply verified ID tokens; all URLs are operator-configured HTTPS endpoints.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode, urlparse

from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import RedirectResponse

_COOKIE = "rizzler_session"
_CSRF = "rizzler_csrf"
_FLOW = "rizzler_oidc_flow"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str
    authorize_url: str
    token_url: str
    jwks_url: str
    client_id: str
    redirect_uri: str
    client_secret: str = ""

    def __post_init__(self):
        for field in ("issuer", "authorize_url", "token_url", "jwks_url", "redirect_uri"):
            url = urlparse(getattr(self, field))
            if (url.scheme != "https" or not url.hostname or url.username or
                    url.password or url.fragment or url.query and field == "issuer"):
                raise ValueError("OIDC endpoints must be explicit HTTPS URLs")
        if not self.client_id or len(self.client_id) > 256:
            raise ValueError("Invalid OIDC client ID")
        if urlparse(self.redirect_uri).path != "/auth/callback":
            raise ValueError("OIDC redirect must terminate at /auth/callback")


class SessionStore:
    """Durable, short-lived, hashed opaque credentials. Not a user directory."""

    def __init__(self, root: Path):
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / "identity.sqlite3"
        with self._db() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS sessions(
                digest TEXT PRIMARY KEY, owner TEXT NOT NULL, csrf TEXT NOT NULL,
                expires INTEGER NOT NULL, created INTEGER NOT NULL)""")
            con.execute("CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(owner,created)")

    @contextmanager
    def _db(self):
        con = sqlite3.connect(self.path, timeout=15)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA busy_timeout=15000")
            with con:
                yield con
        finally:
            con.close()

    def issue(self, owner: str, ttl: int = 3600) -> tuple[str, str]:
        if not re.fullmatch(r"u_[a-f0-9]{40}", owner) or not 60 <= ttl <= 86400:
            raise ValueError("Invalid subject or lifetime")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = int(time.time())
        with self._db() as con:
            con.execute("DELETE FROM sessions WHERE expires<=?", (now,))
            con.execute("INSERT INTO sessions VALUES(?,?,?,?,?)",
                        (_sha(token), owner, _sha(csrf), now + ttl, now))
            rows = con.execute("SELECT digest FROM sessions WHERE owner=? ORDER BY created DESC,digest DESC",
                               (owner,)).fetchall()
            for old in rows[10:]:
                con.execute("DELETE FROM sessions WHERE digest=?", (old[0],))
        return token, csrf

    def validate(self, token: str, csrf: str | None = None) -> str:
        if not isinstance(token, str) or len(token) > 128 or not token:
            raise PermissionError("No valid session")
        with self._db() as con:
            row = con.execute("SELECT owner,csrf,expires FROM sessions WHERE digest=?",
                              (_sha(token),)).fetchone()
        if not row or row[2] <= time.time():
            raise PermissionError("Session expired or revoked")
        if csrf is not None and not hmac.compare_digest(row[1], _sha(csrf)):
            raise PermissionError("Invalid CSRF token")
        return row[0]

    def revoke(self, token: str):
        if token and len(token) <= 128:
            with self._db() as con:
                con.execute("DELETE FROM sessions WHERE digest=?", (_sha(token),))

    def rotate(self, token: str, csrf: str) -> tuple[str, str]:
        """Old session is invalidated in the same serializable SQLite transaction."""
        if not token or not csrf:
            raise PermissionError("Missing session")
        now = int(time.time())
        with self._db() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT owner,csrf,expires FROM sessions WHERE digest=?",
                              (_sha(token),)).fetchone()
            if not row or row[2] <= now or not hmac.compare_digest(row[1], _sha(csrf)):
                raise PermissionError("Invalid or expired session")
            new_token, new_csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            con.execute("DELETE FROM sessions WHERE digest=?", (_sha(token),))
            con.execute("INSERT INTO sessions VALUES(?,?,?,?,?)",
                        (_sha(new_token), row[0], _sha(new_csrf), now + 3600, now))
        return new_token, new_csrf


class Identity:
    def __init__(self, settings: OIDCSettings, root: Path, secret: str):
        if len(secret.encode()) < 32:
            raise ValueError("Session signing secret must be >=32 bytes")
        self.settings, self.sessions = settings, SessionStore(root)
        self.key = secret.encode("utf-8")

    def _flow(self, data: dict) -> str:
        body = _b64(json.dumps(data, separators=(",", ":")).encode())
        signature = _b64(hmac.digest(self.key, body.encode(), "sha256"))
        return body + "." + signature

    def _verify_flow(self, token: str) -> dict:
        try:
            body, sig = token.split(".")
            if not hmac.compare_digest(_b64(hmac.digest(self.key, body.encode(), "sha256")), sig):
                raise ValueError()
            data = json.loads(_unb64(body))
            if not 0 <= time.time() - int(data["issued"]) <= 300:
                raise ValueError()
            for part in ("state", "nonce", "verifier"):
                if not isinstance(data[part], str) or len(data[part]) < 32:
                    raise ValueError()
            return data
        except (ValueError, KeyError, TypeError, UnicodeError, OverflowError) as exc:
            raise PermissionError("OIDC flow expired or invalid") from None

    def _cookies(self, response, token: str, csrf: str):
        response.set_cookie(_COOKIE, token, httponly=True, secure=True,
                            samesite="lax", max_age=3600, path="/")
        response.set_cookie(_CSRF, csrf, httponly=False, secure=True,
                            samesite="strict", max_age=3600, path="/")

    def clear_cookies(self, response):
        for name in (_COOKIE, _CSRF, _FLOW):
            response.delete_cookie(name, path="/", secure=True, samesite="lax")

    def login(self):
        verifier, nonce, state = (secrets.token_urlsafe(40) for _ in range(3))
        challenge = _b64(hashlib.sha256(verifier.encode()).digest())
        params = {"client_id": self.settings.client_id,
                  "response_type": "code", "scope": "openid profile email",
                  "redirect_uri": self.settings.redirect_uri,
                  "state": state, "nonce": nonce, "code_challenge": challenge,
                  "code_challenge_method": "S256"}
        url = self.settings.authorize_url + "?" + urlencode(params)
        response = RedirectResponse(url, status_code=302)
        response.set_cookie(_FLOW, self._flow({"verifier": verifier, "nonce": nonce,
                           "state": state, "issued": int(time.time())}), httponly=True,
                           secure=True, samesite="lax", max_age=300, path="/")
        return response

    async def exchange(self, code: str, state: str, flow: str, provider_iss: str | None):
        if not isinstance(code, str) or not 1 <= len(code) <= 4096:
            raise PermissionError("Invalid authorization code")
        info = self._verify_flow(flow)
        if not hmac.compare_digest(info["state"], state):
            raise PermissionError("OIDC state mismatch")
        if provider_iss is not None and provider_iss.rstrip("/") != self.settings.issuer.rstrip("/"):
            raise PermissionError("OIDC issuer mismatch")
        import httpx
        import jwt
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            payload = {"grant_type": "authorization_code", "code": code,
                       "redirect_uri": self.settings.redirect_uri,
                       "client_id": self.settings.client_id,
                       "code_verifier": info["verifier"]}
            if self.settings.client_secret:
                payload["client_secret"] = self.settings.client_secret
            response = await client.post(self.settings.token_url, data=payload)
            response.raise_for_status()
            identity_token = response.json().get("id_token")
            if not isinstance(identity_token, str) or len(identity_token) > 16384:
                raise PermissionError("Provider did not return an ID token")
            jwks = await client.get(self.settings.jwks_url)
            jwks.raise_for_status()
            keys = jwks.json().get("keys", [])
        header = jwt.get_unverified_header(identity_token)
        if header.get("alg") not in ("RS256", "ES256"):
            raise PermissionError("OIDC signature algorithm not allowed")
        key = next((k for k in keys if k.get("kid") == header.get("kid")
                    and k.get("kty") in ("RSA", "EC") and k.get("use", "sig") == "sig"), None)
        if key is None:
            raise PermissionError("OIDC signing key not found")
        decoded = jwt.decode(identity_token, jwt.PyJWK.from_dict(key).key,
            algorithms=["RS256", "ES256"], audience=self.settings.client_id,
            issuer=self.settings.issuer, options={"require": ["sub", "iat", "exp", "iss", "aud"]},
            leeway=30)
        if not hmac.compare_digest(str(decoded.get("nonce", "")), info["nonce"]):
            raise PermissionError("OIDC nonce mismatch")
        sub = decoded.get("sub")
        if not isinstance(sub, str) or not 1 <= len(sub) <= 512:
            raise PermissionError("OIDC subject missing")
        owner = "u_" + hashlib.sha256(
            (self.settings.issuer + "\0" + sub).encode()).hexdigest()[:40]
        return self.sessions.issue(owner)

    def owner(self, request: Request | WebSocket, *, mutate: bool = False):
        token = request.cookies.get(_COOKIE, "")
        try:
            if mutate:
                csrf = request.headers.get("x-csrf-token", "")
                origin = request.headers.get("origin")
                redirect = urlparse(self.settings.redirect_uri)
                public_origin = f"{redirect.scheme}://{redirect.netloc}"
                if not origin or origin != public_origin:
                    raise PermissionError("Request origin rejected")
                if not csrf or not hmac.compare_digest(csrf, request.cookies.get(_CSRF, "")):
                    raise PermissionError("CSRF cookie mismatch")
                return self.sessions.validate(token, csrf=csrf)
            return self.sessions.validate(token)
        except PermissionError:
            raise HTTPException(status_code=403 if mutate else 401,
                                detail="Authentication required") from None

    def ws_owner(self, ws: WebSocket) -> str:
        try:
            return self.sessions.validate(ws.cookies.get(_COOKIE, ""))
        except PermissionError as exc:
            raise PermissionError("Authentication required") from None
