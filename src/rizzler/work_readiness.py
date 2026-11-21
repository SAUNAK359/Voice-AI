"""V26 stage-aware task readiness.

A document that has not yet been generated is pending execution, not missing
source evidence. This module never grants tool permissions or pretends that
unfinished deliverables are complete. Existing V25 coverage remains readable.
"""
from __future__ import annotations

from copy import deepcopy

EVIDENCE_STATES=frozenset({"supported","partial","unknown"})
EXECUTION_STATES=frozenset({
    "execution_pending","execution_running","candidate_review",
    "qualified","blocked","failed"})
READINESS_STATES=EVIDENCE_STATES|EXECUTION_STATES
POST_SOURCE_KINDS=frozenset({"deliverable","quality"})


def requirement_phase(requirement: dict) -> str:
    """Based on the typed requirement kind, never keyword triggers."""
    if not isinstance(requirement,dict):
        raise ValueError("Malformed outcome requirement")
    return ("execution" if requirement.get("kind") in POST_SOURCE_KINDS
            else "evidence")


def phase_aware_coverage(coverage: list[dict],requirements: list[dict]) -> list[dict]:
    """Non-destructive upgrade of V25 supervisor coverage to V26 phase states.

    This transformation only applies to actual deliverable and quality
    obligations. It does NOT waive evidence needed by analysis, comparison,
    methodology or visualization requirements, nor fabricate citations.
    """
    if not isinstance(coverage,list) or not isinstance(requirements,list):
        raise ValueError("Malformed coverage requirements")
    by_id={r.get("id"):r for r in requirements if isinstance(r,dict)}
    if len(by_id)!=len(requirements):
        raise ValueError("Invalid requirement IDs")
    normalized=[]
    for item in coverage:
        if not isinstance(item,dict) or item.get("id") not in by_id:
            raise ValueError("Coverage refers to unavailable requirement")
        copy=deepcopy(item)
        if requirement_phase(by_id[item["id"]])=="execution":
            if copy.get("status") in ("unknown","partial"):
                copy["status"]="execution_pending"
                copy["evidence_refs"]=[]
            elif copy.get("status")=="supported" and not copy.get("evidence_refs"):
                # A model cannot assert that a not-yet-produced output is done
                # at a pre-artifact checkpoint. Even if upstream evidence is
                # ready, the output's status is separate.
                copy["status"]="execution_pending"
        normalized.append(copy)
    return normalized


def evidence_readiness(coverage: list[dict],requirements: list[dict]) -> bool:
    """Only pre-execution evidence matters to source readiness."""
    by_id={r["id"]:r for r in requirements}
    for item in coverage:
        if item["id"] not in by_id:
            raise ValueError("Unknown requirement")
        if requirement_phase(by_id[item["id"]])=="evidence" and item["status"]=="unknown":
            return False
    return True


def is_pending_output_only(coverage: list[dict],requirements: list[dict]) -> bool:
    """True only if all evidence is ready, and pending work is a deliverable."""
    by_id={r["id"]:r for r in requirements}
    return (evidence_readiness(coverage,requirements) and
            any(item.get("status")=="execution_pending" and
                requirement_phase(by_id[item["id"]])=="execution"
                for item in coverage))
