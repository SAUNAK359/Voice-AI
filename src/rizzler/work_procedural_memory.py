"""Opt-in, owner-isolated procedural learning ledger.

Stores only bounded status categories, never prompts, source texts, personal
facts, tool payloads, transcripts or provider responses. Generated procedural
hints use a separate encrypted memory namespace from user-visible memory.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
import time

from .work_agents import SPECS

CODES=frozenset((
    "ok", "quality_rejected", "quality_review_failed",
    "quality_repair_failed", "quality_validation_failed",
    "research_evidence_missing", "research_planning_invalid",
    "provider_unavailable", "provider_rate_limited",
    "local_admission_busy", "model_decision_invalid",
    "artifact_storage_unavailable", "planning_output_invalid",
    "deep_synthesis_failed", "agent_execution_failed",
))
RETENTION_DAYS=30


def enabled() -> bool:
    return (os.environ.get("RIZZLER_MEMORY_ENABLED","0")=="1" and
            os.environ.get("RIZZLER_LANGMEM_ENABLED","0")=="1")


class ProceduralLedger:
    def __init__(self, root: str | Path, key: str):
        if not isinstance(key,str) or len(key.encode())<32:
            raise ValueError("Procedural memory requires independent encryption key")
        self.key=hashlib.sha256(b"rizzler-procedural-owner-v23\0"+key.encode()).digest()
        root=Path(root)
        if root.is_symlink():
            raise ValueError("Procedural memory root must not be a symlink")
        self.root=root.resolve()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.root/"procedural_signals.sqlite3"
        self.hints_root=self.root/"encrypted_hints"
        self.secret=key
        with self._tx() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS signals(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_tag TEXT NOT NULL,
                specialist TEXT NOT NULL,
                category TEXT NOT NULL,
                at INTEGER NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS procedural_owner
                ON signals(owner_tag,specialist,seq)""")
            db.execute("""CREATE TABLE IF NOT EXISTS reflections(
                owner_tag TEXT NOT NULL,
                specialist TEXT NOT NULL,
                last_seq INTEGER NOT NULL,
                at INTEGER NOT NULL,
                PRIMARY KEY(owner_tag,specialist))""")
            db.execute("""CREATE TABLE IF NOT EXISTS reflection_claims(
                owner_tag TEXT NOT NULL,
                specialist TEXT NOT NULL,
                expires INTEGER NOT NULL,
                PRIMARY KEY(owner_tag,specialist))""")

    @contextmanager
    def _tx(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db
        finally:
            db.close()

    def tag(self, owner: str) -> str:
        from .memory import MemoryStore
        owner=MemoryStore._owner(owner)
        return hmac.new(self.key,owner.encode(),"sha256").hexdigest()

    def record(self, owner: str, specialist: str, category: str) -> None:
        if specialist not in SPECS or category not in CODES:
            raise ValueError("Unregistered procedural outcome")
        tag=self.tag(owner)
        now=int(time.time())
        with self._tx() as db:
            db.execute("INSERT INTO signals(owner_tag,specialist,category,at) "
                       "VALUES(?,?,?,?)",(tag,specialist,category,now))
            db.execute("DELETE FROM signals WHERE at<?",(now-RETENTION_DAYS*86400,))
            db.execute("""DELETE FROM signals WHERE seq IN (
                SELECT seq FROM signals WHERE owner_tag=?
                ORDER BY seq DESC LIMIT -1 OFFSET 160)""",(tag,))

    def guidance(self, owner: str, specialist: str, *, limit=2) -> list[str]:
        if specialist not in SPECS or not 1<=limit<=3:
            raise ValueError("Invalid procedural retrieval")
        from .memory import MemoryStore
        store=MemoryStore(self.hints_root,self.secret,limit=40,ttl_days=30)
        prefix=specialist+": "
        return [row["text"][len(prefix):] for row in store.list(self.tag(owner))
                if row["text"].startswith(prefix)][:limit]

    def delete_owner(self, owner: str) -> None:
        """Apply explicit delete-all to procedural signals and encrypted hints."""
        from .memory import MemoryStore
        tag=self.tag(owner)
        with self._tx() as db:
            db.execute("DELETE FROM signals WHERE owner_tag=?",(tag,))
            db.execute("DELETE FROM reflections WHERE owner_tag=?",(tag,))
            db.execute("DELETE FROM reflection_claims WHERE owner_tag=?",(tag,))
        store=MemoryStore(self.hints_root,self.secret,limit=40,ttl_days=30)
        store.delete(tag)

    def due(self) -> dict | None:
        """One owner-specific aggregate ready for low-priority LangMem reflection."""
        with self._tx() as db:
            rows=db.execute("""SELECT s.owner_tag,s.specialist,
                MAX(s.seq) AS newest, COUNT(*) AS n
                FROM signals s LEFT JOIN reflections r
                  ON r.owner_tag=s.owner_tag AND r.specialist=s.specialist
                WHERE s.seq>COALESCE(r.last_seq,0)
                GROUP BY s.owner_tag,s.specialist
                HAVING n>=4 ORDER BY MAX(s.seq) ASC LIMIT 1""").fetchall()
            if not rows:return None
            tag,specialist,newest,n=rows[0]
            stats=db.execute("""SELECT category,COUNT(*) FROM signals
                 WHERE owner_tag=? AND specialist=? AND seq<=?
                 GROUP BY category ORDER BY category""",
                 (tag,specialist,newest)).fetchall()
        return {"owner_tag":tag,"specialist":specialist,"last_seq":newest,
                "signal_count":n,"categories":dict(stats)}

    def claim_due(self) -> dict | None:
        """Atomically reserve an aggregate for one background reflection worker."""
        now=int(time.time())
        with self._tx() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("""SELECT s.owner_tag,s.specialist,
                MAX(s.seq) AS newest, COUNT(*) AS n
                FROM signals s LEFT JOIN reflections r
                  ON r.owner_tag=s.owner_tag AND r.specialist=s.specialist
                LEFT JOIN reflection_claims c
                  ON c.owner_tag=s.owner_tag AND c.specialist=s.specialist
                WHERE s.seq>COALESCE(r.last_seq,0)
                  AND COALESCE(c.expires,0)<=?
                GROUP BY s.owner_tag,s.specialist
                HAVING n>=4 ORDER BY MAX(s.seq) ASC LIMIT 1""",(now,)).fetchone()
            if row is None:return None
            tag,specialist,newest,count=row
            db.execute("""INSERT INTO reflection_claims(owner_tag,specialist,expires)
                VALUES(?,?,?) ON CONFLICT(owner_tag,specialist)
                DO UPDATE SET expires=excluded.expires""",
                (tag,specialist,now+120))
            stats=db.execute("""SELECT category,COUNT(*) FROM signals
                 WHERE owner_tag=? AND specialist=? AND seq<=?
                 GROUP BY category ORDER BY category""",
                 (tag,specialist,newest)).fetchall()
        return {"owner_tag":tag,"specialist":specialist,"last_seq":newest,
                "signal_count":count,"categories":dict(stats)}

    def commit_reflection(self, batch: dict, hint: str | None) -> bool:
        """Save a provisional operational hint only after strict validation."""
        specialist=batch["specialist"]
        if hint is not None and (not isinstance(hint,str) or
                                 not 18 <= len(hint.strip()) <= 300):
            raise ValueError("Invalid provisional procedural hint")
        with self._tx() as db:
            db.execute("BEGIN IMMEDIATE")
            claim=db.execute("""SELECT expires FROM reflection_claims
                  WHERE owner_tag=? AND specialist=?""",
                  (batch["owner_tag"],specialist)).fetchone()
            if claim is None or claim[0]<int(time.time()):
                raise RuntimeError("Stale or revoked procedural reflection")
            if hint is not None:
                from .memory import MemoryStore
                store=MemoryStore(self.hints_root,self.secret,limit=40,ttl_days=30)
                store.remember(batch["owner_tag"],specialist+": "+hint.strip())
            db.execute("""INSERT INTO reflections(owner_tag,specialist,last_seq,at)
                VALUES(?,?,?,?) ON CONFLICT(owner_tag,specialist)
                DO UPDATE SET last_seq=excluded.last_seq,at=excluded.at""",
                (batch["owner_tag"],specialist,batch["last_seq"],int(time.time())))
            db.execute("DELETE FROM reflection_claims WHERE owner_tag=? AND specialist=?",
                       (batch["owner_tag"],specialist))
        return bool(hint)


def from_environment() -> ProceduralLedger | None:
    if not enabled():
        return None
    root=os.environ.get("RIZZLER_MEMORY_ROOT","").strip()
    if not root:
        work=os.environ.get("RIZZLER_WORK_ROOT","").strip()
        if not work:raise RuntimeError("LangMem requires persistent memory root")
        root=str(Path(work)/"private_memory")
    key=os.environ.get("RIZZLER_MEMORY_KEY","")
    return ProceduralLedger(Path(root)/"procedural_v23",key)


def delete_all_for_owner(owner: str) -> None:
    """Delete historical procedural memory even if future learning was turned off."""
    root=os.environ.get("RIZZLER_MEMORY_ROOT","").strip()
    if not root:
        work=os.environ.get("RIZZLER_WORK_ROOT","").strip()
        if not work:return
        root=str(Path(work)/"private_memory")
    target=Path(root)/"procedural_v23"
    if not target.exists():
        return
    key=os.environ.get("RIZZLER_MEMORY_KEY","")
    ProceduralLedger(target,key).delete_owner(owner)


def record_outcome(owner: str, specialist: str, category: str) -> None:
    ledger=from_environment()
    if ledger is not None:
        ledger.record(owner,specialist,category)


def procedural_guidance(owner: str,specialist: str) -> list[str]:
    ledger=from_environment()
    return ledger.guidance(owner,specialist) if ledger is not None else []
