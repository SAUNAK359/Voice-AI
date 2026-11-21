"""V26 Proof-Carrying Context Fabric: typed, bounded, authoritative task state.

This module implements a minimal, strict v2 graph and permission-filtered
context views without promoting model prose or provider URL metadata to proof.
Existing ArtifactIR(v1) remains authoritative until explicitly migrated.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re

SCHEMA=2
KINDS=frozenset({
    "goal","requirement","source","evidence_span","fact","metric",
    "hypothesis","insight","recommendation","decision","task",
    "artifact_component","review_finding","repair_action","memory_record",
    "uncertainty"})
LINKS=frozenset({
    "satisfies","supported_by","contradicts","derived_from",
    "belongs_to","depends_on","visualizes","computed_by",
    "invalidates","reviewed_by","supersedes","requires_consent",
    "available_to"})
STATES=frozenset({
    "unknown","provider_attributed","retrieved","computed_verified",
    "source_verified","hypothesis","analysis","human_approved"})
VERIFIED=frozenset({"computed_verified","source_verified","human_approved"})
SAFE_ID=re.compile(r"^[a-z][a-z0-9_]{0,40}:[a-zA-Z0-9_.-]{1,100}$")
HEX64=re.compile(r"^[a-f0-9]{64}$")
MAX_OBJECTS=512
MAX_EDGES=1536
MAX_OUTPUT_BYTES=2_000_000
REQUIRED_CORE=frozenset({"goal","requirement","metric","insight","uncertainty"})
REQUIRED_FIELDS=frozenset({
    "id","kind","status","statement","source_ids",
    "unit","scope","critical","audience_tags","digest"})


def canonical(data: object) -> str:
    return json.dumps(data,sort_keys=True,ensure_ascii=False,
                      separators=(",",":"),allow_nan=False)


def digest(data: object) -> str:
    return hashlib.sha256(canonical(data).encode("utf-8")).hexdigest()


def _text(value: object,*,max_len=3500) -> str:
    if not isinstance(value,str) or len(value)>max_len:
        raise ValueError("Invalid bounded context text")
    return value


def _ids(ids: object, *, limit=16) -> tuple[str,...]:
    if not isinstance(ids,(tuple,list)) or len(ids)>limit:
        raise ValueError("Invalid evidence/dependency references")
    if any(not isinstance(i,str) or not SAFE_ID.fullmatch(i) for i in ids):
        raise ValueError("Malformed context reference")
    if len(set(ids))!=len(ids):
        raise ValueError("Duplicate context references")
    return tuple(ids)


def validate_node(record: dict) -> dict:
    if not isinstance(record,dict) or set(record)!=REQUIRED_FIELDS:
        raise ValueError("Context node has unknown/missing fields")
    if (not isinstance(record["id"],str) or
            not SAFE_ID.fullmatch(record["id"]) or
            not isinstance(record["kind"],str) or
            record["kind"] not in KINDS or
            not record["id"].startswith(record["kind"]+":")):
        raise ValueError("Invalid typed node identity")
    status=record["status"]
    if status not in STATES:
        raise ValueError("Invalid trust state")
    statement=_text(record["statement"])
    if not statement.strip() or not isinstance(record["critical"],bool):
        raise ValueError("Empty statement or malformed criticality")
    if not isinstance(record["unit"],str) or len(record["unit"])>70:
        raise ValueError("Missing/invalid measurement unit")
    scope=record["scope"]
    if (not isinstance(scope,dict) or set(scope)-{
            "time","geography","population","dimension","source_method","note"}
            or any(not isinstance(v,str) or len(v)>400
                   for v in scope.values())):
        raise ValueError("Invalid bounded metric/source scope")
    sources=_ids(record["source_ids"],limit=24)
    audience=_ids(record["audience_tags"],limit=12)
    if record["kind"]=="metric":
        if not record["unit"]:
            raise ValueError("Numerical metric unit must be explicit, even if unspecified")
        if status=="computed_verified" and not sources:
            raise ValueError("Computed metric has no source receipt")
    if status in VERIFIED and record["kind"] in (
            "source","evidence_span","fact","metric","insight",
            "recommendation") and not sources:
        raise ValueError("Verified claim requires a proof lineage")
    source_digest=record["digest"]
    if source_digest is not None and (
            not isinstance(source_digest,str) or
            not HEX64.fullmatch(source_digest)):
        raise ValueError("Invalid proof digest")
    if status=="source_verified" and source_digest is None:
        raise ValueError("Source verified without extracted content hash")
    return {
        **record,"source_ids":list(sources),"audience_tags":list(audience),
        "scope":dict(scope)}


def validate_graph(graph: dict) -> dict:
    if not isinstance(graph,dict) or set(graph)!={
            "schema_version","job_id","owner","task_digest","nodes",
            "edges","revision"}:
        raise ValueError("Invalid versioned graph envelope")
    if graph["schema_version"]!=SCHEMA:
        raise ValueError("Graph schema mismatch")
    if any(not isinstance(graph[k],str) or not graph[k].strip()
           or len(graph[k])>128 for k in ("job_id","owner")):
        raise ValueError("Missing owner/job scope")
    if not isinstance(graph["task_digest"],str) or not HEX64.fullmatch(
            graph["task_digest"]):
        raise ValueError("Invalid immutable task fingerprint")
    nodes=graph["nodes"]
    edges=graph["edges"]
    if (not isinstance(nodes,list) or len(nodes)>MAX_OBJECTS
            or not isinstance(edges,list) or len(edges)>MAX_EDGES):
        raise ValueError("Graph exceeds bounded node/edge budget")
    checked=[validate_node(node) for node in nodes]
    ids=[node["id"] for node in checked]
    if len(ids)!=len(set(ids)):
        raise ValueError("Duplicate typed context node")
    available=set(ids)
    for item in checked:
        # External proof receipts are allowed only through the explicit
        # source: / evidence_span: / metric: namespaces, or dataset digest.
        for ref in item["source_ids"]:
            if (ref not in available and
                    not ref.startswith(("source:","evidence_span:"))):
                raise ValueError("Unsupported proof lineage namespace")
    for edge in edges:
        if not isinstance(edge,dict) or set(edge)!={"from","to","relation"}:
            raise ValueError("Malformed relationship")
        if (edge["relation"] not in LINKS or edge["from"] not in available
                or edge["to"] not in available):
            raise ValueError("Dangling or unauthorized graph relationship")
    payload={key:graph[key] for key in graph if key!="revision"}
    if not isinstance(graph["revision"],str) or graph["revision"]!=digest(payload):
        raise ValueError("Graph revision checksum disagrees")
    if len(canonical(graph).encode("utf-8"))>MAX_OUTPUT_BYTES:
        raise ValueError("Context graph exceeds byte limit")
    return {**graph,"nodes":checked}


def new_graph(*,owner: str,job_id: str,task: dict) -> dict:
    if not isinstance(task,dict):
        raise ValueError("Invalid immutable task contract")
    candidate={"schema_version":SCHEMA,"owner":owner,
               "job_id":job_id,"task_digest":digest(task),
               "nodes":[],"edges":[]}
    return validate_graph({**candidate,"revision":digest(candidate)})


def commit_nodes(graph: dict, *,nodes: list[dict],
                 edges: list[dict] | None = None, 
                 owner: str,job_id: str,base_revision: str) -> dict:
    """Compare-and-swap, never last-writer-wins model text."""
    baseline=validate_graph(graph)
    if (baseline["owner"]!=owner or baseline["job_id"]!=job_id
            or baseline["revision"]!=base_revision):
        raise PermissionError("Stale or cross-owner context mutation")
    old={n["id"]:n for n in baseline["nodes"]}
    for node in nodes:
        checked=validate_node(node)
        if checked["id"] in old and old[checked["id"]]!=checked:
            raise ValueError("Existing context fact cannot be overwritten")
        old[checked["id"]]=checked
    links=baseline["edges"]+list(edges or [])
    unique={canonical(item):item for item in links}
    updated={key:deepcopy(value) for key,value in baseline.items()
             if key!="revision"}
    updated["nodes"]=list(old.values())
    updated["edges"]=list(unique.values())
    return validate_graph({**updated,"revision":digest(updated)})


def select_context(graph: dict, *, owner: str,job_id: str,
                   recipient: str, required_ids: list[str],
                   optional_ids: list[str] | None = None,
                   byte_budget: int = 24_000) -> dict:
    """Role-filtered view; required facts/caveats cannot silently truncate."""
    checked=validate_graph(graph)
    if checked["owner"]!=owner or checked["job_id"]!=job_id:
        raise PermissionError("Cross-tenant context access")
    if not isinstance(recipient,str) or not 2<=len(recipient)<=100:
        raise ValueError("Invalid recipient")
    if not 1500<=byte_budget<=100_000:
        raise ValueError("Invalid context budget")
    wanted=_ids(required_ids,limit=80)
    option=_ids(optional_ids or [],limit=200)
    all_nodes={node["id"]:node for node in checked["nodes"]}
    missing=set(wanted)-all_nodes.keys()
    if missing:
        raise ValueError("Required proof nodes unavailable")
    # Always include the critical goal, constraints, and caveats even if
    # the planner accidentally omitted their IDs.
    pinned={node["id"] for node in checked["nodes"]
            if node["critical"] and node["kind"] in
            ("goal","requirement","metric","uncertainty")}
    compulsory=set(wanted)|pinned
    permitted={n["id"] for n in checked["nodes"] 
               if not n["audience_tags"] or recipient in n["audience_tags"]}
    if not compulsory<=permitted:
        raise PermissionError("Required context is not authorized for this role")
    selection=[all_nodes[n["id"]] for n in checked["nodes"] if n["id"] in compulsory]
    base={"schema_version":SCHEMA,"owner":owner,"job_id":job_id,
          "context_revision":checked["revision"],"recipient":recipient,
          "required_ids":sorted(compulsory),
          "nodes":selection,"omitted_optional_ids":[]}
    if len(canonical(base).encode("utf-8"))>byte_budget:
        raise ValueError("Mandatory proof will not fit; request budget expansion")
    omitted=[]
    for id_ in option:
        if id_ in compulsory:
            continue
        if id_ not in permitted or id_ not in all_nodes:
            omitted.append(id_)
            continue
        base["nodes"].append(all_nodes[id_])
        if len(canonical(base).encode("utf-8"))>byte_budget:
            base["nodes"].pop()
            omitted.append(id_)
    base["omitted_optional_ids"]=omitted
    base["completeness"]={
        "mandatory_included":True,"omitted_optional_count":len(omitted)}
    base["integrity"]=digest({key:v for key,v in base.items() if key!="integrity"})
    return base


def verify_context_packet(packet: dict,*,owner: str,job_id: str,
                          recipient: str,revision: str) -> None:
    if not isinstance(packet,dict) or (
            packet.get("owner"),packet.get("job_id"),
            packet.get("recipient"),packet.get("context_revision"))!=(
                owner,job_id,recipient,revision):
        raise PermissionError("Invalid context ownership or revision")
    proof={key:v for key,v in packet.items() if key!="integrity"}
    if packet.get("integrity")!=digest(proof):
        raise ValueError("Context slice integrity changed")
    visible={n["id"] for n in packet.get("nodes",[])}
    if not set(packet.get("required_ids",[]))<=visible:
        raise ValueError("Required context silently omitted")
