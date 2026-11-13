"""Durable owner-scoped API admission for one shared SQLite filesystem.

Never records user IDs, bearer tokens, filenames, paths or prompts. One
transaction serializes checks across processes sharing the same DB file.
These request *rates* are independent of PDF document sizes/page counts and
of Google's actual billing or its provider-side quota.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import math
from pathlib import Path
import sqlite3
import time

CLASSES=("standard","expensive","upload","work","connect")


class RateExceeded(RuntimeError):
    def __init__(self,retry_after:int):
        self.retry_after=retry_after
        super().__init__("Private request rate exceeded")


def classify(method:str,path:str)->str:
    """Classify trusted server route+verb; never incorporate URL identifiers."""
    if path=="/api/turn" and method=="POST":
        return "expensive"
    if path=="/api/visual/ask" and method=="POST":
        return "expensive"
    if path.startswith("/api/pdf/documents/") and path.endswith("/research") and method=="POST":
        return "expensive"
    if path.startswith("/api/pdf/research/") and path.endswith("/resume") and method=="POST":
        return "expensive"
    if path.startswith("/api/pdf/documents/") and path.endswith("/chunks") and method=="PUT":
        return "upload"
    if path.startswith("/api/pdf/documents/") and "/chunks/" in path and method=="PUT":
        return "upload"
    if path.startswith("/api/work/jobs") and method=="POST":
        return "work"
    if path.startswith("/api/voice/jobs") and method=="POST":
        return "work"
    if path=="/ws":
        return "connect"
    return "standard"


class OwnerRateLedger:
    """Atomic 60-second fixed-window buckets; cross-process when filesystem shared."""

    def __init__(self,path:str|Path,key:str,limits:dict[str,int]|None=None):
        path=Path(path)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("Admission ledger must be an absolute non-symlink file")
        if not isinstance(key,str) or len(key.encode())<32:
            raise ValueError("Admission digest key must have 32+ bytes")
        self.path=path
        self.key=hashlib.sha256(b"rizzler-owner-admission-v11\0"+key.encode()).digest()
        self.limits=limits or {
            "standard":1200,"expensive":90,"upload":3600,"work":60,"connect":90,
        }
        if set(self.limits)!=set(CLASSES) or any(
                type(v) is not int or v<1 or v>1_000_000 for v in self.limits.values()):
            raise ValueError("Invalid admission rate configuration")
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS rates(
                 subject BLOB NOT NULL, kind TEXT NOT NULL,
                 epoch INTEGER NOT NULL, count INTEGER NOT NULL,
                 PRIMARY KEY(subject,kind,epoch))""")
            db.execute("CREATE INDEX IF NOT EXISTS rates_epoch ON rates(epoch)")

    @contextmanager
    def _db(self):
        db=sqlite3.connect(self.path,timeout=15)
        try:
            db.execute("PRAGMA busy_timeout=15000")
            with db:
                yield db
        finally:
            db.close()

    def admit(self,owner:str,kind:str,at:float|None=None)->int:
        if not isinstance(owner,str) or not 1<=len(owner)<=256:
            raise ValueError("Invalid admission owner")
        if kind not in CLASSES:
            raise ValueError("Invalid request classification")
        now=time.time() if at is None else at
        if not isinstance(now,(int,float)) or not math.isfinite(now) or now<0:
            raise ValueError("Invalid admission timestamp")
        epoch=int(now//60)
        digest=hmac.digest(self.key,owner.encode(),hashlib.sha256)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            count=db.execute("""SELECT count FROM rates
                WHERE subject=? AND kind=? AND epoch=?""",
                (digest,kind,epoch)).fetchone()
            if count and count[0]>=self.limits[kind]:
                raise RateExceeded(max(1,math.ceil((epoch+1)*60-now)))
            db.execute("""INSERT INTO rates(subject,kind,epoch,count)
                VALUES(?,?,?,1)
                ON CONFLICT(subject,kind,epoch)
                DO UPDATE SET count=count+1""",(digest,kind,epoch))
            # Bound old metadata; never erase the current window.
            db.execute("DELETE FROM rates WHERE epoch<?",(epoch-120,))
        return self.limits[kind]-(count[0]+1 if count else 1)

    def snapshot(self)->dict:
        epoch=int(time.time()//60)
        with self._db() as db:
            rows=db.execute("""SELECT kind,SUM(count) FROM rates
                WHERE epoch=? GROUP BY kind""",(epoch,)).fetchall()
        return {"window_seconds":60,"requests_by_class":dict(rows),
                "limits_per_owner":dict(self.limits),
                "scope":"shared SQLite filesystem; subjects are keyed HMAC digests",
                "note":"Not an IP/WAF limiter, not GPU capacity or Gemini billing"}
