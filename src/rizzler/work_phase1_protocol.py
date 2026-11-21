"""Phase-1 authoritative Work evidence handoff and source-investigation protocol.

The immutable job envelope, current PCCF graph and typed source obligations are
one contract across preflight, recovery, authorship and final QA. LLMs own
semantic decisions; these validators do not create permissions, source truth
or new requirements. No user content, provider messages or secrets are logged.
"""
from __future__ import annotations

import hashlib
import json

from .work_outcome_phases import phase_projection, validate_evidence_request

SOURCE_AGENTS=frozenset({"research","sql_analytics","user"})
REQUEST_KEYS=frozenset({"recipient","question","reason","blocking","requirement_id"})


class HandoffContractError(ValueError):
    """A source or execution handoff violated the approved job contract."""


def source_obligations(requirements: list[dict]) -> list[dict]:
    """Only phase-qualified source work can authorize an investigation."""
    phases={p["id"]:p for p in phase_projection(requirements)}
    return [
        {"id":row["id"],"kind":row["kind"],
         "obligation":str(row.get("obligation",""))[:300]}
        for row in requirements if phases[row["id"]]["evidence_required"]
    ]


def validate_source_request(request: dict, *, requirements: list[dict],
                            permitted: frozenset[str]) -> dict:
    """The same strict schema is enforced at ALL V26 producer/consumer edges.

    A permitted upstream tool cannot infer its own requirement id; an output
    obligation is never a substitute for source evidence. No silent repair or
    textual keyword-based permission escalation is allowed.
    """
    if (not isinstance(request,dict) or set(request)!=REQUEST_KEYS
            or not isinstance(permitted,frozenset)):
        raise HandoffContractError("Invalid source request envelope")
    recipient=request["recipient"]
    if (recipient not in SOURCE_AGENTS
            or (recipient!="user" and recipient not in permitted)
            or type(request["blocking"]) is not bool
            or not isinstance(request["question"],str)
            or not 16<=len(request["question"].strip())<=650
            or not isinstance(request["reason"],str)
            or not 15<=len(request["reason"].strip())<=500):
        raise HandoffContractError("Source request has invalid scope or payload")
    try:
        validate_evidence_request(request,requirements)
    except ValueError as exc:
        raise HandoffContractError("Source request lacks an approved source obligation") from exc
    return request


def immutable_task_digest(payload: dict) -> str:
    """The L0 authorization digest is identical before and after PCCF build."""
    from .work_context_fabric import _sha as canonical_sha
    if (not isinstance(payload,dict)
            or not isinstance(payload.get("objective"),str)
            or not payload["objective"].strip()
            or not isinstance(payload.get("deliverables"),list)
            or not payload["deliverables"]
            or any(not isinstance(fmt,str) or not fmt
                   for fmt in payload["deliverables"])):
        raise HandoffContractError("Immutable user goal or output scope missing")
    return canonical_sha({
        "original_objective":payload["objective"],
        "authorized_formats":payload["deliverables"]})


def validate_upstream_handoff(*, payload: dict,owner: str,
                              job_id: str,specialist: str) -> dict:
    """Bind pre-graph research/SQL/orchestration to the same L0 user scope."""
    from .work_agents import plan
    if (not isinstance(owner,str) or not 3<=len(owner)<=150
            or not isinstance(job_id,str) or not 3<=len(job_id)<=150
            or specialist not in ("research","sql_analytics","orchestrator")):
        raise HandoffContractError("Invalid upstream identity or agent scope")
    if specialist not in {x.name for x in plan(payload)}:
        raise HandoffContractError("Upstream agent is not authorized by job plan")
    return {"schema_version":1,"owner_scope":owner,"job_id":job_id,
            "recipient_specialist":specialist,
            "immutable_goal_digest":immutable_task_digest(payload)}


def validate_task_handoff(graph: dict, *, payload: dict,
                          owner: str, job_id: str, specialist: str) -> dict:
    """Verify exact task, tenant, source revision and critical metric lineage.

    Task/format authority comes from the persisted user job, never an LLM
    context block. The returned manifest is a compact proof reference; its
    hash is derived from a canonical bounded packet, not a provider summary.
    """
    from .work_context_fabric import validate_fabric, READERS
    from .work_context_fabric import ContextAccessDenied

    validate_fabric(graph)
    if (graph["owner_scope"]!=owner or graph["job_id"]!=job_id
            or specialist not in READERS):
        raise ContextAccessDenied("Owner, job or specialist handoff mismatch")
    if (not isinstance(payload,dict)
            or not isinstance(payload.get("objective"),str)
            or not isinstance(payload.get("deliverables"),list)
            or not payload["deliverables"]):
        raise HandoffContractError("Persisted user goal is unavailable")
    if immutable_task_digest(payload)!=graph["immutable_goal_digest"]:
        raise HandoffContractError("Source graph does not match immutable job")
    original=next((item for item in graph["nodes"]
                   if item["id"]=="goal:original"),None)
    if (original is None or original["kind"]!="goal"
            or original["status"]!="approved"
            or original["data"].get("original_objective")!=payload["objective"]
            or original["data"].get("authorized_formats")!=payload["deliverables"]):
        raise HandoffContractError("Goal graph attempts to change user authorization")
    required=sorted(item["id"] for item in graph["nodes"]
                    if item["kind"]=="requirement")
    sources=sorted(item["id"] for item in graph["nodes"]
                   if item["kind"]=="source")
    critical=sorted(item["id"] for item in graph["nodes"]
                    if item["kind"]=="metric" and
                    item["data"].get("critical") is True)
    uncertainties=sorted(item["id"] for item in graph["nodes"]
                         if item["kind"]=="uncertainty")
    packet={"schema_version":1,
            "job_id":job_id,"owner_scope":owner,
            "recipient_specialist":specialist,
            "immutable_goal_digest":graph["immutable_goal_digest"],
            "context_revision":graph["context_revision"],
            "authorized_formats":list(payload["deliverables"]),
            "requirement_ids":required,
            "source_ids":sources,
            "critical_metric_ids":critical,
            "uncertainty_ids":uncertainties}
    packet["handoff_sha256"]=hashlib.sha256(json.dumps(
        packet,sort_keys=True,ensure_ascii=False,
        separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()
    return packet


def assert_current_handoff(handoff: dict, graph: dict, *,
                           payload: dict, owner: str,
                           job_id: str, specialist: str) -> None:
    """A renderer may not commit output against a superseded source revision."""
    expected=validate_task_handoff(
        graph,payload=payload,owner=owner,
        job_id=job_id,specialist=specialist)
    if handoff!=expected:
        raise HandoffContractError("Source context changed during specialist execution")
