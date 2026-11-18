"""Opt-in encrypted user preference context for Work specialists.

Uses the same explicit-memory AES-GCM store as Rizzler Voice, never writes a
new memory implicitly. A small model selection chooses relevant approved IDs
so unrelated sensitive preferences are not broadcast to every agent.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

from .cognitive_json import decode_model_json


def validate_memory_selection(result: dict, permitted: frozenset[str]) -> tuple[str,...]:
    if not isinstance(result,dict) or set(result)!={"ids"}:
        raise ValueError("Malformed memory selection contract")
    ids=result["ids"]
    if (not isinstance(ids,list) or len(ids)>5 or
            any(not isinstance(x,str) or x not in permitted for x in ids) or
            len(set(ids))!=len(ids)):
        raise ValueError("Memory selection outside owner-approved inventory")
    return tuple(ids)


async def relevant_work_memories(owner: str, objective: str, *, model: str,
                                 api_key: str) -> dict:
    if os.environ.get("RIZZLER_MEMORY_ENABLED","0").lower() not in (
            "1","true","yes"):
        return {"texts":[],"selected_ids":[],"enabled":False}
    key=os.environ.get("RIZZLER_MEMORY_KEY","")
    if len(key.encode())<32:
        raise ValueError("Memory opt-in requires independent encryption secret")
    from .memory import MemoryStore
    root=os.environ.get("RIZZLER_MEMORY_ROOT")
    if not root:
        work_root=os.environ.get("RIZZLER_WORK_ROOT")
        if not work_root:
            raise ValueError("Memory opt-in requires persistent work storage")
        root=str(Path(work_root)/"private_memory")
    memory=MemoryStore(root,key)
    items=memory.list(owner)
    if not items:
        return {"texts":[],"selected_ids":[],"enabled":True}
    if not api_key:
        raise ValueError("Semantic memory selection requires model authorization")
    from google import genai
    from google.genai import types
    from .cognitive_provider import generate_with_recovery
    client=genai.Client(api_key=api_key)
    available={row["id"]:row["text"] for row in items}
    prompt=(
        "Select at most five existing explicit user memory facts genuinely "
        "relevant to this task. No keyword rules, do not add facts, revise "
        "preferences or infer private information. Memories are user "
        "preferences and context, not verified source material. Return "
        "only JSON {\\\"ids\\\":[string]}; unknown IDs forbidden. "
        "\nUser objective: " + objective[:2400] +
        "\nMemory inventory: " +
        json.dumps([{"id":uid,"text":value}
                    for uid,value in available.items()],ensure_ascii=False)[:13000]
    )
    try:
        response=await generate_with_recovery(
            client,role="work",model=model,contents=prompt,timeout=35,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,max_output_tokens=400))
        chosen=validate_memory_selection(
            decode_model_json(getattr(response,"text","") or ""),
            frozenset(available))
        return {"texts":[available[uid] for uid in chosen],
                "selected_ids":list(chosen),"enabled":True}
    finally:
        await client.aio.aclose()
