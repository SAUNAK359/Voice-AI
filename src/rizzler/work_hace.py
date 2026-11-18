"""HACE: hierarchy-aware, dependency-validated specialist tool microprograms.

The model may author a program, but only registered handlers execute. No tool
string is evaluated as code. The engine rejects cyclic graphs, oversized
arguments, unauthorized capabilities and missing predecessor results.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Awaitable, Callable

from .work_skill_packages import SkillPackage

_NODE = re.compile(r"^[a-z][a-z0-9_]{1,36}$")


class HACEContractError(ValueError):
    pass


@dataclass(frozen=True)
class MicroTask:
    id: str
    capability: str
    depth: int
    depends_on: tuple[str, ...]
    arguments: dict


def validate_program(raw: dict, package: SkillPackage) -> tuple[MicroTask, ...]:
    if not isinstance(raw,dict) or set(raw) != {"version","tasks"} or raw["version"] != 1:
        raise HACEContractError("Unsupported capability program")
    tasks = raw["tasks"]
    if not isinstance(tasks,list) or not 1 <= len(tasks) <= min(24,package.max_calls):
        raise HACEContractError("Program exceeds specialist budget")
    known=set()
    result=[]
    for node in tasks:
        if not isinstance(node,dict) or set(node) != {
                "id","capability","depth","depends_on","arguments"}:
            raise HACEContractError("Malformed microtask")
        name, capability = node["id"],node["capability"]
        if (not isinstance(name,str) or not _NODE.fullmatch(name) or name in known
                or capability not in package.capabilities):
            raise HACEContractError("Unregistered capability or duplicate step")
        deps=node["depends_on"]
        if (not isinstance(deps,list) or len(deps)!=len(set(deps)) or
                any(dep not in known for dep in deps)):
            raise HACEContractError("Forward, cyclic or invalid microtask dependency")
        depth=node["depth"]
        if (type(depth) is not int or not 0 <= depth <= package.max_depth or
                (deps and depth < max(
                    step.depth for step in result if step.id in deps))):
            raise HACEContractError("Microtask violates progressive domain depth")
        args=node["arguments"]
        if type(args) is not dict or len(args)>15:
            raise HACEContractError("Microtask arguments malformed")
        try:
            encoded=json.dumps(args,ensure_ascii=False,allow_nan=False)
        except (ValueError,TypeError) as exc:
            raise HACEContractError("Arguments are not JSON serializable") from exc
        if len(encoded.encode()) > 6000:
            raise HACEContractError("Microtask input budget exceeded")
        result.append(MicroTask(name,capability,depth,tuple(deps),args))
        known.add(name)
    return tuple(result)


async def execute_program(
    tasks: tuple[MicroTask, ...],
    handlers: dict[str,Callable[...,Awaitable[Any]]],
    *, max_parallel: int = 3,
    on_event: Callable[[str,str],None] | None = None,
) -> dict[str,Any]:
    """Execute independent tasks with structured outputs and bounded fanout.

    Per-output size is limited to avoid flooding downstream model context.
    Previous completed waves survive an independent sibling's exception in
    the parent WorkStore; no unfinished result is falsely declared complete.
    """
    if not 1 <= max_parallel <= 3:
        raise HACEContractError("Microtask concurrency must not exceed three")
    completed: dict[str,Any]={}
    pending={item.id:item for item in tasks}
    semaphore=asyncio.Semaphore(max_parallel)
    while pending:
        ready=[item for item in tasks if item.id in pending and
               all(dep in completed for dep in item.depends_on)]
        if not ready:
            raise HACEContractError("Microtask graph is blocked")
        async def invoke(item: MicroTask):
            handler=handlers.get(item.capability)
            if handler is None:
                raise HACEContractError("Handler not registered for "+item.capability)
            async with semaphore:
                if on_event: on_event("microtask_started",item.id)
                outcome=await handler(item.arguments,{
                    dep:completed[dep] for dep in item.depends_on})
                try:
                    packed=json.dumps(outcome,ensure_ascii=False,allow_nan=False)
                except (ValueError,TypeError) as exc:
                    raise HACEContractError("Microtask returned unstructured result") from exc
                if len(packed.encode())>50000:
                    raise HACEContractError("Microtask result exceeds context budget")
                if on_event: on_event("microtask_completed",item.id)
                return outcome
        results=await asyncio.gather(*(invoke(item) for item in ready),
                                     return_exceptions=True)
        errors=[e for e in results if isinstance(e,BaseException)]
        if errors:
            for error in errors:
                if isinstance(error,asyncio.CancelledError):
                    raise error
            raise ExceptionGroup("Capability microtasks failed",errors)
        for item,value in zip(ready,results):
            completed[item.id]=value
            del pending[item.id]
    return completed


def fingerprint(tasks: tuple[MicroTask, ...]) -> str:
    canonical=json.dumps([{"id":x.id,"capability":x.capability,
        "depth":x.depth,"depends_on":list(x.depends_on),
        "arguments":x.arguments} for x in tasks],sort_keys=True,
        separators=(",",":"),ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
