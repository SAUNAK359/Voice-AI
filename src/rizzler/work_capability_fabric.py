"""Bounded capability discovery and compiled, parallel read-only tool programs.

This is NOT arbitrary model-executed Python or a public plugin loader. Only
developer-registered, typed, permission-checked tools may be scheduled.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass
from typing import Callable, Any

_ID = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class CapabilityContractError(ValueError):
    pass


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    handler: Callable[[dict], Any]
    keys: frozenset[str]
    permissions: frozenset[str] = frozenset()
    timeout_seconds: float = 20

    def __post_init__(self):
        if (not _ID.fullmatch(self.name) or not 12 <= len(self.description) <= 400
                or not callable(self.handler)
                or not 0.1 <= self.timeout_seconds <= 120):
            raise CapabilityContractError("Invalid registered capability")

    def public(self):
        return {"name": self.name, "description": self.description,
                "arguments": sorted(self.keys),
                "permissions": sorted(self.permissions)}


class CapabilityFabric:
    """A host-controlled registry with DAG validation and scoped tool execution."""

    def __init__(self, capabilities: list[Capability], *, max_parallel: int = 8):
        if not 1 <= max_parallel <= 32:
            raise CapabilityContractError("Invalid tool concurrency")
        self.catalog = {}
        for cap in capabilities:
            if cap.name in self.catalog:
                raise CapabilityContractError("Duplicate registered capability")
            self.catalog[cap.name] = cap
        self.max_parallel = max_parallel

    def discover(self, query: str, allowed: set[str], *, limit=8) -> list[dict]:
        """Lightweight local lookup never consumes another cloud model call."""
        if not isinstance(query, str) or len(query) > 400 or not 1 <= limit <= 15:
            raise CapabilityContractError("Invalid capability query")
        words = set(re.findall(r"[a-z0-9]{3,}",query.lower()))
        ranked = []
        for cap in self.catalog.values():
            if not cap.permissions.issubset(allowed):
                continue
            fields=set(re.findall(r"[a-z0-9]{3,}", (cap.name+" "+cap.description).lower()))
            score=len(fields & words)
            ranked.append((score,cap.name,cap))
        ranked.sort(key=lambda v:(-v[0],v[1]))
        return [cap.public() for score,_,cap in ranked[:limit]
                if score or not words]

    def compile(self, proposal: dict, allowed: set[str]) -> tuple[dict, ...]:
        if type(proposal) is not dict or set(proposal) != {"steps"}:
            raise CapabilityContractError("Invalid tool program")
        steps=proposal["steps"]
        if type(steps) is not list or not 1 <= len(steps) <= 24:
            raise CapabilityContractError("Tool program budget exceeded")
        known=set()
        accepted=[]
        for task in steps:
            if type(task) is not dict or set(task) != {
                    "id","tool","arguments","depends_on"}:
                raise CapabilityContractError("Invalid tool step")
            sid,name,arguments,deps=(task[k] for k in
                                    ("id","tool","arguments","depends_on"))
            if (type(sid) is not str or not _ID.fullmatch(sid) or sid in known
                    or type(name) is not str or name not in self.catalog):
                raise CapabilityContractError("Unrecognized tool step")
            cap=self.catalog[name]
            if not cap.permissions.issubset(allowed):
                raise PermissionError("Tool capability not authorized")
            if type(arguments) is not dict or set(arguments) != cap.keys:
                raise CapabilityContractError("Tool argument schema mismatch")
            if len(json.dumps(arguments,ensure_ascii=False,default=str)) > 6000:
                raise CapabilityContractError("Tool arguments exceed budget")
            if (type(deps) is not list or len(deps) != len(set(deps)) or
                    any(type(d) is not str or d not in known for d in deps)):
                raise CapabilityContractError("Unknown or forward tool dependency")
            known.add(sid)
            accepted.append(task)
        return tuple(accepted)

    async def execute(self, proposal: dict, allowed: set[str]) -> dict:
        tasks=self.compile(proposal,allowed)
        limiter=asyncio.Semaphore(self.max_parallel)
        pending={x["id"]:x for x in tasks}
        results={}
        while pending:
            ready=[x for x in tasks if x["id"] in pending
                   and set(x["depends_on"]).issubset(results)]
            if not ready:
                raise CapabilityContractError("Tool execution DAG cannot advance")
            async def perform(step):
                cap=self.catalog[step["tool"]]
                async with limiter:
                    async def invoke():
                        if inspect.iscoroutinefunction(cap.handler):
                            return await cap.handler(dict(step["arguments"]))
                        return await asyncio.to_thread(cap.handler,
                                                       dict(step["arguments"]))
                    result=await asyncio.wait_for(invoke(),cap.timeout_seconds)
                    # No file handles, arbitrary classes or source objects leave the fabric.
                    serialized=json.dumps(result,ensure_ascii=False,allow_nan=False)
                    if len(serialized.encode())>24000:
                        raise CapabilityContractError("Tool result exceeds safe budget")
                    return step["id"],json.loads(serialized)
            # Return exceptions instead of silently swallowing results.
            batch=await asyncio.gather(*(perform(step) for step in ready))
            results.update(batch)
            for step in ready:
                del pending[step["id"]]
        return {"status":"completed","results":results}


def read_only_fabric(source_text: str, sources: list[str],
                     skills: dict[str,str]) -> CapabilityFabric:
    """Scoped pure tools for Deep Agents; user text never becomes executable code."""
    if len(source_text)>70000 or len(sources)>32:
        raise CapabilityContractError("Oversized evidence context")
    def inventory(_):
        return {"sources":sources[:24], "source_count":len(sources),
                "evidence_chars":len(source_text),
                "source_claims_verified":False}
    def evidence(args):
        needle=args["query"].casefold().strip()
        if not needle or len(needle)>150:
            raise CapabilityContractError("Invalid evidence query")
        lines=source_text.splitlines()
        matches=[{"line":i+1,"text":line[:450]} for i,line in enumerate(lines)
                 if needle in line.casefold()][:10]
        return {"matches":matches,"verification":"unverified_passage_match"}
    def skill(args):
        name=args["name"]
        if name not in skills:
            raise CapabilityContractError("Specialist skill unavailable")
        return {"specialist":name,"instructions":skills[name][:9000]}
    return CapabilityFabric([
        Capability("source_inventory","Inspect source coverage and attribution, without inventing verification",
                   inventory,frozenset()),
        Capability("evidence_lookup","Locate exact evidence passages in supplied source context",
                   evidence,frozenset({"query"})),
        Capability("skill_reference","Load detailed approved specialist procedures on demand",
                   skill,frozenset({"name"})),
    ],max_parallel=8)
