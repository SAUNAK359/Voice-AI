"""Explicit, owner-scoped, encrypted conversational memory.

Disabled unless RIZZLER_MEMORY_ENABLED and a distinct persistent encryption key
are configured. No implicit summarization or recording of voice transcripts.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

_OWNER = re.compile(r"^[a-zA-Z0-9_-]{4,100}$")
_ID = re.compile(r"^[a-zA-Z0-9_-]{12,32}$")
_SECRET = re.compile(
    r"(?:\b(?:api[_ -]?key|password|private[_ -]?key|secret[_ -]?token|bearer token)\b"
    r"|\bAIza[A-Za-z0-9_-]{20,}\b|\bsk-[a-zA-Z0-9_-]{16,}\b)",
    re.IGNORECASE,
)
_TERMS = re.compile(r"[a-z0-9]{3,32}")
_STOP = frozenset("the and for with about from this that have will your what when where"
                  " why how are was were you can use like want need please tell know".split())


class MemoryDisabled(RuntimeError):
    pass


class MemoryStore:
    """Opt-in encrypted facts; all DB operations use owner-qualified predicates."""

    def __init__(self, root: str | Path, key: str, *, limit: int = 24,
                 ttl_days: int = 30):
        if not isinstance(key, str) or len(key.encode()) < 32:
            raise ValueError("Memory requires an independent >=32-byte secret")
        if not 1 <= limit <= 100 or not 7 <= ttl_days <= 90:
            raise ValueError("Invalid memory retention bounds")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self._aes = AESGCM(hashlib.sha256(b"rizzler-v11-memory\0" + key.encode()).digest())
        self._index_key = hashlib.sha256(b"rizzler-v11-memory-index\0" + key.encode()).digest()
        self.limit, self.ttl_days = limit, ttl_days
        original = Path(root)
        if original.is_symlink():
            raise ValueError("Memory storage must not be symlinked")
        directory = original.resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "memory_v11.sqlite3"
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS memory(
                owner TEXT NOT NULL, id TEXT NOT NULL, digest TEXT NOT NULL,
                ciphertext BLOB NOT NULL, created INTEGER NOT NULL,
                expires INTEGER NOT NULL, PRIMARY KEY(owner,id),
                UNIQUE(owner,digest))""")
            db.execute("CREATE INDEX IF NOT EXISTS memory_ttl ON memory(expires)")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _owner(owner: str) -> str:
        if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
            raise ValueError("Invalid memory owner")
        return owner

    @staticmethod
    def _text(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Memory must be text")
        value = " ".join(value.split())
        if (not 5 <= len(value) <= 500 or _SECRET.search(value) or
                any(ord(c) < 32 for c in value)):
            raise ValueError("Memory must be 5–500 characters and contain no secrets")
        return value

    def _encrypt(self, owner: str, uid: str, text: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._aes.encrypt(nonce, text.encode("utf-8"),
                                         (owner + "\0" + uid).encode())

    def _decrypt(self, owner: str, uid: str, encrypted: bytes) -> str:
        if len(encrypted) < 29:
            raise ValueError("Corrupt encrypted memory")
        return self._aes.decrypt(encrypted[:12], encrypted[12:],
                                 (owner + "\0" + uid).encode()).decode()

    def remember(self, owner: str, text: str) -> dict:
        owner, text = self._owner(owner), self._text(text)
        digest = hmac.digest(self._index_key, (owner + "\0" + text.casefold()).encode(),
                             "sha256").hex()
        now = int(time.time())
        expires = now + self.ttl_days * 86400
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM memory WHERE expires<=?", (now,))
            existing = db.execute("SELECT id,expires FROM memory WHERE owner=? AND digest=?",
                                  (owner,digest)).fetchone()
            if existing:
                return {"id": existing[0], "expires": existing[1], "created": False}
            uid = secrets.token_urlsafe(15)
            db.execute("INSERT INTO memory VALUES(?,?,?,?,?,?)",
                       (owner,uid,digest,self._encrypt(owner,uid,text),now,expires))
            records = db.execute("SELECT id FROM memory WHERE owner=? ORDER BY created DESC,rowid DESC",
                                 (owner,)).fetchall()
            for old in records[self.limit:]:
                db.execute("DELETE FROM memory WHERE owner=? AND id=?", (owner,old[0]))
        return {"id":uid,"expires":expires,"created":True}

    def list(self, owner: str) -> list[dict]:
        owner = self._owner(owner)
        with self._db() as db:
            rows = db.execute(
                "SELECT id,ciphertext,created,expires FROM memory "
                "WHERE owner=? AND expires>? ORDER BY created DESC,id DESC LIMIT ?",
                (owner,int(time.time()),self.limit)).fetchall()
        # Tampered ciphertext fails closed rather than returning partial memory.
        try:
            return [{"id":uid,"text":self._decrypt(owner,uid,enc),
                     "created":created,"expires":expires}
                    for uid,enc,created,expires in rows]
        except Exception as exc:
            raise ValueError("Stored memory integrity check failed") from exc

    def delete(self, owner: str, uid: str | None = None) -> int:
        owner = self._owner(owner)
        if uid is not None and (not isinstance(uid,str) or not _ID.fullmatch(uid)):
            raise ValueError("Invalid memory identifier")
        with self._db() as db:
            result = db.execute(
                "DELETE FROM memory WHERE owner=?" + (" AND id=?" if uid else ""),
                (owner,uid) if uid else (owner,))
            return result.rowcount

    def relevant(self, owner: str, query: str, *, limit: int = 3) -> list[str]:
        if not isinstance(query,str) or not 1 <= limit <= 5:
            raise ValueError("Invalid memory retrieval request")
        terms = set(_TERMS.findall(query.casefold())) - _STOP
        if not terms:
            return []
        scored = []
        for item in self.list(owner):
            matches = terms & (set(_TERMS.findall(item["text"].casefold()))-_STOP)
            if matches:
                scored.append((len(matches), item["created"], item["text"]))
        scored.sort(reverse=True)
        return [text for _,_,text in scored[:limit]]
