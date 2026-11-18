"""Owner-private, quality-gated LangMem learning for Work specialists.

Hot path: encrypted lexical recall (zero LLM calls). Cold path: LangMem
extracts reusable lessons only AFTER authoritative WorkStore final QA and
successful publication. No unverified facts, raw documents, keys or private
chain-of-thought are persisted. Existing Live memory remains separate.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_ALLOWED = frozenset(("research","sql_analytics","orchestrator","powerpoint",
                       "word","excel","pdf_visual","quality"))
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.,:;/()'-]{19,349}$")
_PRIVATE = re.compile(
    r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"https?://\S+|"
    r"AIza[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{16,}|"
    r"\b(?:password|api[_ -]?key|bearer|private[_ -]?token)\b|"
    r"\b\d{8,}\b)", re.IGNORECASE)

def _issue_safe(text: str) -> bool:
    return bool(_SAFE.fullmatch(text) and not _PRIVATE.search(text))



class OperationalLesson(BaseModel):
    """Model-proposed procedural lesson; acceptance still requires real QA evidence."""
    specialist: Literal["research","sql_analytics","orchestrator","powerpoint",
                        "word","excel","pdf_visual","quality"]
    action: str = Field(min_length=20,max_length=250)
    why: str = Field(min_length=15,max_length=250)
    source_issue: str = Field(min_length=15,max_length=250)
    confidence: float = Field(ge=0,le=1)


def enabled() -> bool:
    return (os.environ.get("RIZZLER_LANGMEM_ENABLED","0") == "1"
            and os.environ.get("RIZZLER_MEMORY_ENABLED","0") == "1")


def _store():
    if not enabled():
        return None
    from .memory import MemoryStore
    root=os.environ.get("RIZZLER_WORK_ROOT","")
    key=os.environ.get("RIZZLER_MEMORY_KEY","")
    if not root or len(key.encode("utf-8"))<32:
        raise RuntimeError("LangMem requires encrypted persistent work memory")
    # Isolate procedural lessons from Live user preferences. Distinct derived
    # encryption secret prevents identical ciphertext-domain keys.
    derived=hashlib.sha256(
        b"rizzler-work-lessons-v23\0"+key.encode("utf-8")).hexdigest()
    return MemoryStore(Path(root)/"work_lessons",derived,limit=72,ttl_days=90)


def recall(owner: str, objective: str, *, limit: int=4) -> list[str]:
    """Bounded fast recall, never interpreted as instructions or verified facts."""
    if not enabled():
        return []
    memory=_store()
    return memory.relevant(owner,objective[:4000],limit=min(5,max(1,limit)))


def _safe_lesson(raw: OperationalLesson, defects: list[dict]) -> str | None:
    if raw.confidence < 0.85 or raw.specialist not in _ALLOWED:
        return None
    # The model cannot cite an entirely invented QA issue. The source issue
    # must match a recorded actual Quality defect, not a generated statement.
    issues=[str(x.get("problem",""))[:250] for x in defects if isinstance(x,dict)]
    if not any(raw.source_issue.casefold() in issue.casefold() for issue in issues):
        return None
    if (not _issue_safe(raw.action) or not _issue_safe(raw.why) or
            _PRIVATE.search(raw.source_issue)):
        return None
    text=(f"[verified-work:{raw.specialist}] {raw.action}; "
          f"reason: {raw.why}")
    return text if len(text)<=500 else None


async def consolidate_completed_job(store, owner: str, jid: str,
                                    cfg=None, manager_factory=None) -> dict:
    """Run only after successful publication; failures cannot undo the job.

    Never use unverified user content as permanent memory. Only the list of
    deterministic or reviewer-observed QA defects is offered to LangMem; its
    candidate suggestions must cite a real issue to be stored.
    """
    if not enabled():
        return {"status":"disabled","saved":0}
    job=store.get(owner,jid)
    if job["status"]!="completed":
        return {"status":"not_verified","saved":0}
    record=store.quality_report(owner,jid)
    verdict=record.get("quality") if isinstance(record,dict) else None
    if not isinstance(verdict,dict) or verdict.get("passed") is not True:
        return {"status":"not_verified","saved":0}
    episodes=store.quality_feedback(owner,jid)
    defects=[entry for episode in episodes
             for entry in episode.get("findings",[]) if isinstance(entry,dict)]
    # QA descriptions can contain untrusted quoted user material. Exclude
    # possible personal/secret data before calling an external memory model.
    defects=[item for item in defects
             if _issue_safe(str(item.get("problem","")))][:8]
    if not defects:
        return {"status":"no_safe_learning_signal","saved":0}
    if cfg is None:
        from .work_dynamic import WorkModelConfig
        cfg=WorkModelConfig.from_env()
    if manager_factory is None:
        from langmem import create_memory_manager
        manager_factory=create_memory_manager
    from .work_deepagents import _model
    manager=manager_factory(
        _model(cfg), schemas=[OperationalLesson],
        instructions=(
            "Extract ONLY a reusable technical corrective procedure supported "
            "by recorded QA defect observations. Do not store personal data, "
            "uploaded source text, credentials, general hallucinated facts, "
            "unverified performance results, or hidden reasoning. "
            "The output must quote a specific existing source_issue string. "
            "If no evidence-supported lesson exists, return no memory."
        ))
    # Only already-sanitized QA issues pass this boundary, no original prompts,
    # raw documents or secrets. Cap to bound inference time/cost.
    safe_issues=[{"kind":str(item.get("kind",""))[:60],
                  "problem":str(item.get("problem",""))[:250]}
                 for item in defects[:8]]
    conversation=[{"role":"user",
                   "content":"Quality-assurance failure observations: "+str(safe_issues)[:3000]}]
    async with asyncio.timeout(min(45,float(cfg.request_timeout))):
        if hasattr(manager,"ainvoke"):
            proposals=await manager.ainvoke({"messages":conversation})
        else:
            proposals=await manager(conversation)
    candidates=[]
    for entry in (proposals or [])[:8]:
        value=getattr(entry,"content",None)
        if value is None and isinstance(entry,(list,tuple)) and len(entry)>1:
            value=entry[1]
        if isinstance(value,OperationalLesson):
            candidates.append(value)
        elif isinstance(value,dict):
            try:candidates.append(OperationalLesson.model_validate(value))
            except ValueError:pass
    saved=0
    private=_store()
    for item in candidates[:3]:
        line=_safe_lesson(item,defects)
        if not line:
            continue
        if private.remember(owner,line)["created"]:
            saved+=1
    return {"status":"consolidated","saved":saved}
