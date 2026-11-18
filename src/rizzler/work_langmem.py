"""LangMem-assisted, sleep-time procedural reflection for HACE specialists.

Never mines conversations or uploaded files. Only opted-in, owner-isolated
stable success/error counters are sent to LangMem. Candidate improvements are
stored as encrypted ADVISORY hints, never installed as executable instructions.
The model uses the same three-slot Gemini gate as foreground Work calls.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from .work_procedural_memory import ProceduralLedger, from_environment

logger=logging.getLogger("rizzler.work.langmem")


async def reflect_once(ledger: ProceduralLedger | None = None, *,
                       model=None, factory=None) -> dict:
    ledger=ledger if ledger is not None else from_environment()
    if ledger is None:
        return {"status":"disabled"}
    batch=ledger.claim_due()
    if batch is None:
        return {"status":"idle"}
    # Avoid spending a model call to optimize a specialist with no observed
    # difficulty: successful calls alone are not evidence of a useful fix.
    findings={key:count for key,count in batch["categories"].items()
              if key!="ok"}
    if not findings:
        ledger.commit_reflection(batch,None)
        return {"status":"insufficient_failures","specialist":batch["specialist"]}
    if model is None:
        from .work_deepagents import _model
        from .work_dynamic import WorkModelConfig
        model=_model(WorkModelConfig.from_env())
    if factory is None:
        from langmem import create_memory_manager
        factory=create_memory_manager
    from pydantic import BaseModel,Field

    class ProcedureHint(BaseModel):
        specialist: str
        intervention: str = Field(min_length=18,max_length=300)
        rationale: str = Field(min_length=16,max_length=280)

    manager=factory(
        model,
        schemas=[ProcedureHint],
        instructions=(
            "You are an offline agent-runtime quality coach. You see ONLY "
            "anonymized, owner-isolated aggregate statuses; no user data, "
            "files, prompts, or hidden reasoning. Recommend one concrete "
            "skill-level verification or execution improvement, strictly "
            "for the supplied specialist. Do not invent observed failures, "
            "provider quotas, benchmark results, new tool access or private "
            "information. Do not recommend disabling security checks, "
            "publication gates or source verification. Return one typed "
            "ProcedureHint. Never request new permissions. The hint is merely "
            "advisory and cannot modify executable skills."),
        enable_inserts=True, enable_updates=False, enable_deletes=False)
    sample={"specialist":batch["specialist"],"failures":findings,
            "observations":batch["signal_count"]}
    try:
        async with asyncio.timeout(60):
            results=await manager.ainvoke({
                "messages":[{"role":"user","content":json.dumps(sample)}],
                "max_steps":2})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("LangMem reflection failed: %s",
                       "model_or_provider_unavailable")
        return {"status":"deferred","specialist":batch["specialist"]}
    suggestion=None
    if isinstance(results,list):
        for extracted in results[:3]:
            value=getattr(extracted,"content",None)
            if isinstance(value,ProcedureHint):
                candidate=value
            elif isinstance(value,dict):
                try:candidate=ProcedureHint.model_validate(value)
                except Exception:continue
            else:
                continue
            if candidate.specialist!=batch["specialist"]:
                continue
            hint=candidate.intervention.strip().replace("\n"," ")
            if (not re.fullmatch(r"[A-Za-z0-9 .,:;()/+-]{18,300}",hint)
                    or any(s in hint.casefold() for s in (
                        "ignore instructions","disable checks","skip qa",
                        "api key","password","access token","private user"))):
                continue
            suggestion=hint
            break
    ledger.commit_reflection(batch,suggestion)
    return {"status":"hint_saved" if suggestion else "no_safe_hint",
            "specialist":batch["specialist"]}


async def periodic_reflection(*, interval_seconds: float = 180) -> None:
    """Low-priority worker-loop task; no Gemini work added to request hot path."""
    if interval_seconds < 60:
        raise ValueError("Memory reflection frequency too high")
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await reflect_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("LangMem reflection cycle deferred")
