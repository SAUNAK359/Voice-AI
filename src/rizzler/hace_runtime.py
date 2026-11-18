"""HACE execution contracts: bounded hierarchical briefs and approved DAG scheduling.

The hierarchy contains public task objectives and evidence requirements, never
private reasoning. Model-generated briefs are advisory; they cannot create tools,
grant permissions, modify the persisted WorkStore plan, or execute side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

MAX_BRIEFS = 48
MAX_DEPTH = 8


@dataclass(frozen=True)
class StageBrief:
    id: str
    depth: int
    parent: str | None
    specialist: str
    objective: str
    output_contract: str
    evidence_refs: tuple[str, ...] = ()


def topological_waves(graph: dict, approved: frozenset[str]) -> tuple[tuple[str, ...], ...]:
    """Schedule exactly the immutable, approved DAG; fail on missing/cyclic steps.

    Validation is deliberately independent from dict insertion order so future
    planners can reorder compatible tasks without rewriting the worker.
    """
    from .task_planning import validate_graph

    validate_graph(graph, approved)
    ordered = tuple(step["id"] for step in graph["steps"])
    pending = {step["id"]: frozenset(step["depends_on"]) for step in graph["steps"]}
    done: set[str] = set()
    waves: list[tuple[str, ...]] = []
    while pending:
        ready = tuple(name for name in ordered if name in pending and pending[name] <= done)
        if not ready:
            raise ValueError("Execution graph cannot be scheduled")
        waves.append(ready)
        done.update(ready)
        for name in ready:
            del pending[name]
    return tuple(waves)


def validate_stage_briefs(
    document: Mapping[str, Any], *, approved: frozenset[str],
    evidence_ids: frozenset[str] = frozenset(),
) -> tuple[StageBrief, ...]:
    """Validate an optional model-authored inverse-pyramid task description.

    Stage 1 describes the broad objective; deeper stages progressively specify
    verifiable deliverables. The already-approved WorkStore DAG remains the only
    executable authority. No tool arguments, shell commands, URLs or secrets
    enter this contract.
    """
    if not isinstance(document, dict) or set(document) != {"schema_version", "stages"}:
        raise ValueError("Invalid hierarchy envelope")
    if document["schema_version"] != 23:
        raise ValueError("Unsupported hierarchy version")
    raw = document["stages"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_BRIEFS:
        raise ValueError("Hierarchy size outside configured bounds")
    seen: dict[str, StageBrief] = {}
    result: list[StageBrief] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {
            "id", "depth", "parent", "specialist", "objective",
            "output_contract", "evidence_refs"
        }:
            raise ValueError("Unknown hierarchy fields")
        ident, depth, parent = item["id"], item["depth"], item["parent"]
        specialist = item["specialist"]
        if not isinstance(ident, str) or not 1 <= len(ident) <= 48 or not all(
            x.isascii() and (x.isalnum() or x in "_-") for x in ident
        ) or ident in seen:
            raise ValueError("Invalid or duplicate stage ID")
        if type(depth) is not int or not 1 <= depth <= MAX_DEPTH:
            raise ValueError("Invalid stage depth")
        if specialist not in approved:
            raise PermissionError("Stage requested an unapproved specialist")
        if depth == 1:
            if parent is not None:
                raise ValueError("Root stage must not have a parent")
        elif not isinstance(parent, str) or parent not in seen or seen[parent].depth >= depth:
            raise ValueError("Stage has no valid shallower parent")
        for key in ("objective", "output_contract"):
            val = item[key]
            if not isinstance(val, str) or not 8 <= len(val.strip()) <= 1200:
                raise ValueError("Stage description outside bounds")
        refs = item["evidence_refs"]
        if not isinstance(refs, list) or len(refs) > 16 or len(set(refs)) != len(refs):
            raise ValueError("Invalid evidence references")
        if any(not isinstance(ref, str) or ref not in evidence_ids for ref in refs):
            raise ValueError("Stage references evidence outside the approved source set")
        stage = StageBrief(ident, depth, parent, specialist,
                           item["objective"].strip(), item["output_contract"].strip(),
                           tuple(refs))
        seen[ident] = stage
        result.append(stage)
    if result[0].depth != 1 or len([s for s in result if s.depth == 1]) != 1:
        raise ValueError("Hierarchy must have exactly one general root stage")
    # A stage cannot disappear from the approved execution scope. Model output
    # cannot silently omit an authorized deliverable, even though the briefs
    # themselves are never used to authorize actions.
    if not approved.issubset({s.specialist for s in result}):
        raise ValueError("Hierarchy omitted an approved specialist")
    return tuple(result)


def public_stage_summary(stages: Sequence[StageBrief]) -> list[dict]:
    """Serialize public task contracts without revealing model deliberation."""
    return [
        {"id": s.id, "depth": s.depth, "parent": s.parent,
         "specialist": s.specialist, "objective": s.objective,
         "output_contract": s.output_contract, "evidence_refs": list(s.evidence_refs)}
        for s in stages
    ]
