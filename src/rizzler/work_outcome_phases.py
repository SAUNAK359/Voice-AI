"""Phase-aware outcome obligations; evidence before output, quality after output.

Pre-artifact readiness may only ask for facts, data and user clarification.
An unrendered document is a pending authorized action, NEVER missing research.
This module is a v1-compatible projection; the immutable goal stays unchanged.
"""
from __future__ import annotations

EVIDENCE="NEEDS_EVIDENCE"
EVIDENCE_READY="EVIDENCE_READY"
EXECUTION_PENDING="EXECUTION_PENDING"
EXECUTION_RUNNING="EXECUTION_RUNNING"
CANDIDATE_REVIEW="CANDIDATE_REVIEW"
QUALIFIED="QUALIFIED"
BLOCKED="BLOCKED"
FAILED="FAILED"

OUTPUT_KINDS=frozenset({"deliverable","quality","visualization"})
SOURCE_KINDS=frozenset({"answer","evidence","analysis","comparison","method"})
REQUIREMENT_KINDS=OUTPUT_KINDS|SOURCE_KINDS


def phase_projection(requirements: list[dict], *,
                     stage: str="pre_artifact") -> list[dict]:
    if stage not in ("pre_artifact","rendering","review","completed"):
        raise ValueError("Unknown outcome lifecycle stage")
    if not isinstance(requirements,list) or len(requirements)>50:
        raise ValueError("Malformed outcome requirement list")
    result=[]
    seen=set()
    for item in requirements:
        if (not isinstance(item,dict)
                or type(item.get("id")) is not str
                or not item["id"] or item["id"] in seen
                or item.get("kind") not in REQUIREMENT_KINDS):
            raise ValueError("Invalid phase-aware obligation")
        seen.add(item["id"])
        is_output=item["kind"] in OUTPUT_KINDS
        phase=(
            EXECUTION_PENDING if stage=="pre_artifact" and is_output else
            EXECUTION_RUNNING if stage=="rendering" and is_output else
            CANDIDATE_REVIEW if stage=="review" and is_output else
            QUALIFIED if stage=="completed" and is_output else
            EVIDENCE_READY if stage=="completed" else
            EVIDENCE
        )
        result.append({"id":item["id"],"kind":item["kind"],
                       "phase":phase,
                       "evidence_required":not is_output})
    return result


def normalize_context_coverage(coverage: list[dict],
                               requirements: list[dict], *,
                               stage: str="pre_artifact") -> list[dict]:
    """Never count future output absence as a research or SQL deficiency."""
    projection={p["id"]:p for p in phase_projection(requirements,stage=stage)}
    if not isinstance(coverage,list):
        raise ValueError("Coverage is not a list")
    output=[]
    for record in coverage:
        if not isinstance(record,dict):
            raise ValueError("Malformed reviewer coverage item")
        item=dict(record)
        phase=projection.get(item.get("id"))
        if phase and phase["phase"]==EXECUTION_PENDING:
            # An upstream research supervisor has no authority to certify a
            # future renderer. All such output obligations await execution.
            item["status"]="execution_pending"
            item["evidence_refs"]=[]
        output.append(item)
    return output


def validate_evidence_request(request: dict,
                              requirements: list[dict], *,
                              require_binding: bool=True) -> dict:
    """A source investigation must be explicitly tied to a SOURCE obligation.

    It may not be used to satisfy, pre-empt or circumvent an unbuilt output.
    Literal request text is never used as a keyword-based permission signal.
    """
    if not isinstance(request,dict):
        raise ValueError("Malformed evidence request")
    requirement_id=request.get("requirement_id")
    if requirement_id is None and not require_binding:
        return request
    allowed={item["id"] for item in phase_projection(requirements)
             if item["evidence_required"]}
    if type(requirement_id) is not str or requirement_id not in allowed:
        raise ValueError("Requested investigation is not bound to a source obligation")
    return request


def derive_job_readiness(requirements: list[dict],
                         coverage: list[dict], *,
                         stage: str="pre_artifact") -> dict:
    projections={p["id"]:p for p in phase_projection(requirements,stage=stage)}
    states={}
    for row in normalize_context_coverage(coverage,requirements,stage=stage):
        key=row.get("id")
        if key not in projections or key in states:
            raise ValueError("Invalid or duplicate requirement coverage")
        states[key]=(
            EXECUTION_PENDING if row.get("status")=="execution_pending" else
            EVIDENCE_READY if row.get("status")=="supported" else
            EVIDENCE)
    if set(states)!=set(projections):
        raise ValueError("Missing required evidence review entries")
    evidence_ready=all(
        states[p["id"]]==EVIDENCE_READY for p in projections.values()
        if p["evidence_required"])
    return {"stage":stage,"evidence_ready":evidence_ready,
            "states":states,"artifacts_ready":False}
