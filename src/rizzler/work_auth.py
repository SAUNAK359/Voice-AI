"""Independent Work Agent identity boundary; tokens are issued only by trusted code.

The public API never exchanges the shared voice key for a work bearer token.
An external login/issuer must authenticate a user before calling issue_token.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import re
import time

OWNER = re.compile(r"^[A-Za-z0-9_-]{3,64}$")


def _secret(secret: str) -> bytes:
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise ValueError("Work signing secret must contain at least 32 bytes")
    return secret.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def issue_token(owner: str, secret: str, ttl: int = 900) -> str:
    """Only for authenticated issuers or local development, never an API route."""
    key = _secret(secret)
    if not isinstance(owner, str) or not OWNER.fullmatch(owner) or not 60 <= ttl <= 3600:
        raise ValueError("Invalid token scope")
    payload = _b64(json.dumps(
        {"aud": "rizzler-work-v1", "sub": owner, "exp": int(time.time()) + ttl},
        separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64(hmac.digest(key, payload.encode("ascii"), "sha256"))
    return payload + "." + signature


def verify_token(header: str | None, secret: str) -> str:
    key = _secret(secret)
    if not isinstance(header, str) or not header.startswith("Bearer "):
        raise PermissionError("Work bearer token required")
    token = header[7:]
    if len(token) > 2048 or token.count(".") != 1:
        raise PermissionError("Invalid bearer token")
    body, sig = token.split(".")
    correct = _b64(hmac.digest(key, body.encode("ascii", "ignore"), "sha256"))
    if not hmac.compare_digest(sig, correct):
        raise PermissionError("Invalid bearer token")
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        values = json.loads(raw)
        owner, exp = values["sub"], values["exp"]
        if (values.get("aud") != "rizzler-work-v1" or
                not isinstance(owner, str) or not OWNER.fullmatch(owner) or
                type(exp) is not int or exp <= time.time() or
                exp > time.time() + 3600):
            raise ValueError("Invalid token claims")
        return owner
    except (ValueError, KeyError, TypeError, UnicodeError, OverflowError) as exc:
        raise PermissionError("Invalid bearer token") from None
