"""Proof-Carrying Context Fabric (PCCF), WorkKnowledgeIR v2.

Typed, owner-scoped, content-addressed knowledge across specialized agents.
The task's immovable authorization envelope cannot be expanded by inference.
A source URL is attribution, NOT verified page content. V1 report paragraphs
are narrative CANDIDATES, never promoted into verified claims automatically.

The v2 context adapter is opt-in and reconstructible from the authoritative
WorkStore source checkpoints. Explicit node retrieval is scoped by identity,
revision, capability and purpose; no truncation of hard requirements or caveats.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
import re

VERSION=2
KINDS=frozenset({
    "goal","requirement","source","evidence_span","fact","metric",
    "hypothesis","insight","recommendation","decision","task",
    "artifact_component","review_finding","repair_action",
    "memory_record","uncertainty","narrative_candidate"})
EDGES=frozenset({
    "satisfies","supported_by","contradicts","derived_from",
    "belongs_to","depends_on","visualizes","computed_by","invalidates",
    "reviewed_by","supersedes","requires_consent","available_to"})
ID_PATTERN=re.compile(r"^[a-z][a-z_]*:[A-Za-z0-9_.:-]{1,120}$")
HEX64=re.compile(r"^[0-9a-f]{64}$")
READERS=frozenset({
    "research","sql_analytics","orchestrator","powerpoint","word",
    "excel","pdf_visual","quality","editorial","domain_expert",
    "context_intelligence"})
LIMIT=1500


class ContextIntegrityError(ValueError):
    """Invalid or unsupported proof-bearing knowledge."""


class ContextAccessDenied(PermissionError):
    """Scoped context cannot be exported to this principal/specialist."""


class ContextBudgetExceeded(ValueError):
    """Critical constraints cannot be squeezed into an unsafe prompt."""


def _json(record) -> str:
    return json.dumps(record,ensure_ascii=False,
        sort_keys=True,separators=(",",":"),allow_nan=False)


def _sha(record) -> str:
    return hashlib.sha256(_json(record).encode("utf-8")).hexdigest()


def _ident(value: str):
    if type(value) is not str or not ID_PATTERN.fullmatch(value):
        raise ContextIntegrityError("Invalid typed knowledge ID")
    return value


def node(*,id: str,kind: str,data: dict,dependencies=(),
         status: str="candidate",visibility: str="job") -> dict:
    _ident(id)
    if (kind not in KINDS or not id.startswith(kind+":")
            or type(data) is not dict or
            status not in ("candidate","attributed","computed_summary",
                           "verified","contradicted","unknown","pending",
                           "approved","blocked")
            or visibility not in ("job","specialist","private")
            or not isinstance(dependencies,(list,tuple))
            or len(dependencies)>100):
        raise ContextIntegrityError("Invalid knowledge node contract")
    deps=list(dependencies)
    if len(deps)!=len(set(deps)) or id in deps:
        raise ContextIntegrityError("Duplicate or self-referencing knowledge input")
    for dep in deps:
        _ident(dep)
    try:
        raw=_json(data)
    except (TypeError,ValueError) as exc:
        raise ContextIntegrityError("Knowledge data is not canonical JSON") from exc
    if len(raw.encode("utf-8"))>50000:
        raise ContextIntegrityError("One context node is too large")
    return {"id":id,"kind":kind,"data":data,
            "dependencies":deps,"status":status,"visibility":visibility,
            "content_sha256":_sha({"id":id,"kind":kind,"data":data,
                                   "dependencies":deps,"status":status,
                                   "visibility":visibility})}


def create_fabric(*,owner: str,job_id: str,goal_digest: str,
                  nodes: list[dict],edges: list[dict] | None = None) -> dict:
    if (not isinstance(owner,str) or not 3<=len(owner)<=150
            or not isinstance(job_id,str) or not 3<=len(job_id)<=150
            or not isinstance(goal_digest,str)
            or not HEX64.fullmatch(goal_digest)
            or not isinstance(nodes,list) or len(nodes)>LIMIT):
        raise ContextIntegrityError("Invalid owner, identity or source scope")
    lookup={}
    for item in nodes:
        if not isinstance(item,dict) or set(item)!={
                "id","kind","data","dependencies","status",
                "visibility","content_sha256"}:
            raise ContextIntegrityError("Invalid node fields")
        actual=node(id=item["id"],kind=item["kind"],data=item["data"],
                    dependencies=item["dependencies"],
                    status=item["status"],visibility=item["visibility"])
        if actual!=item or actual["id"] in lookup:
            raise ContextIntegrityError("Corrupt, duplicate or altered knowledge node")
        lookup[item["id"]]=item
    links=edges or []
    if not isinstance(links,list) or len(links)>5000:
        raise ContextIntegrityError("Invalid relationship budget")
    for item in links:
        if (not isinstance(item,dict)
                or set(item)!={"from","to","relation"}
                or item["relation"] not in EDGES
                or item["from"] not in lookup or item["to"] not in lookup):
            raise ContextIntegrityError("Unknown relationship or unauthorized node reference")
    for item in nodes:
        if not set(item["dependencies"])<=set(lookup):
            raise ContextIntegrityError("Knowledge dependency unavailable")
        if item["kind"]=="source" and item["status"]=="verified":
            if (item["data"].get("content_verified") is not True
                    or not isinstance(item["data"].get("content_sha256"),str)
                    or not HEX64.fullmatch(item["data"]["content_sha256"])):
                raise ContextIntegrityError("A URL alone cannot verify source bytes")
        if item["kind"]=="evidence_span" and item["status"]=="verified":
            sources=[lookup[dep] for dep in item["dependencies"]
                     if lookup[dep]["kind"]=="source"
                     and lookup[dep]["status"]=="verified"]
            if not sources or not HEX64.fullmatch(
                    str(item["data"].get("span_sha256",""))):
                raise ContextIntegrityError("Verified span lacks a verified source")
        if item["kind"] in ("fact","insight") and item["status"]=="verified":
            if not item["dependencies"]:
                raise ContextIntegrityError("Claims cannot self-certify as facts")
            for dep in item["dependencies"]:
                inherited=lookup[dep]
                if inherited["status"] not in ("verified","computed_summary"):
                    raise ContextIntegrityError("Verified inference has unverified input")
        if item["kind"]=="metric":
            val=item["data"].get("value")
            if (type(val) not in (int,float) or not math.isfinite(val)
                    or not isinstance(item["data"].get("unit"),str)
                    or not item["data"]["unit"].strip()
                    or not item["dependencies"]):
                raise ContextIntegrityError("Quantitative node lacks value, unit or receipt")
    # No cyclic dependency graph; safety relies on reliable invalidation order.
    active=set()
    done=set()
    def visit(key):
        if key in active:
            raise ContextIntegrityError("Cyclic source or insight dependency")
        if key in done:
            return
        active.add(key)
        for dep in lookup[key]["dependencies"]:
            visit(dep)
        active.remove(key)
        done.add(key)
    for key in lookup:
        visit(key)
    canonical=sorted(nodes,key=lambda item:item["id"])
    links=sorted(links,key=lambda item:(item["from"],item["to"],item["relation"]))
    result={"schema_version":VERSION,"owner_scope":owner,
            "job_id":job_id,"immutable_goal_digest":goal_digest,
            "nodes":canonical,"edges":links}
    result["context_revision"]=_sha(result)
    return result


def validate_fabric(record: dict) -> dict:
    if not isinstance(record,dict) or set(record)!={
            "schema_version","owner_scope","job_id","immutable_goal_digest",
            "nodes","edges","context_revision"} or record["schema_version"]!=VERSION:
        raise ContextIntegrityError("Invalid knowledge graph schema")
    rebuilt=create_fabric(
        owner=record["owner_scope"],job_id=record["job_id"],
        goal_digest=record["immutable_goal_digest"],
        nodes=record["nodes"],edges=record["edges"])
    if rebuilt!=record:
        raise ContextIntegrityError("Context digest or canonical graph mismatch")
    return record


def _authorized(graph: dict,*,owner: str,job_id: str,specialist: str):
    validate_fabric(graph)
    if graph["owner_scope"]!=owner or graph["job_id"]!=job_id:
        raise ContextAccessDenied("Owner or job scope mismatch")
    if specialist not in READERS:
        raise ContextAccessDenied("No authorized specialist capability")


def context_fetch(graph: dict,*,owner: str,job_id: str,
                  specialist: str,ids: list[str],
                  purpose: str,max_bytes: int=10000) -> dict:
    """Owner-authenticated exact-node retrieval with dependency inclusion."""
    _authorized(graph,owner=owner,job_id=job_id,specialist=specialist)
    if (not isinstance(purpose,str) or not 12<=len(purpose)<=400
            or not isinstance(ids,list) or not 1<=len(ids)<=50
            or not 500<=max_bytes<=100000):
        raise ValueError("Invalid bounded context fetch request")
    lookup={item["id"]:item for item in graph["nodes"]}
    if len(ids)!=len(set(ids)) or any(key not in lookup for key in ids):
        raise ContextAccessDenied("Invalid or inaccessible knowledge reference")
    required=set()
    def expand(key):
        if key in required:
            return
        item=lookup[key]
        if item["visibility"]=="private" and specialist!="context_intelligence":
            raise ContextAccessDenied("Private graph node")
        required.add(key)
        for dep in item["dependencies"]:
            expand(dep)
    for key in ids:
        expand(key)
    subset=[lookup[key] for key in sorted(required)]
    if len(_json(subset).encode("utf-8"))>max_bytes:
        raise ContextBudgetExceeded("Mandatory evidence cannot fit requested fetch budget")
    return {"schema_version":VERSION,"revision":graph["context_revision"],
            "requested_ids":ids,"nodes":subset,
            "receipt_sha256":_sha(subset)}


def context_view(graph: dict,*,owner: str,job_id: str,
                 specialist: str,required_ids: list[str] | None = None,
                 optional_ids: list[str] | None = None,
                 max_bytes: int=12000) -> dict:
    """Hard constraints and uncertainties are never silently summarized away."""
    _authorized(graph,owner=owner,job_id=job_id,specialist=specialist)
    if not 1000<=max_bytes<=100000:
        raise ContextBudgetExceeded("Invalid scoped context budget")
    lookup={item["id"]:item for item in graph["nodes"]}
    required={item["id"] for item in graph["nodes"]
              if item["kind"] in ("goal","requirement","uncertainty","metric","insight","recommendation")
              and item["visibility"]!="private"}
    optional=optional_ids if optional_ids is not None else [
        x["id"] for x in graph["nodes"] if x["visibility"]=="job"]
    for name in required_ids or []:
        if name not in lookup:
            raise ContextAccessDenied("Unknown required evidence")
        required.add(name)
    def include(key):
        if key in required:
            return
        required.add(key)
    # Closure is essential to prevent a metric without its input receipt.
    remaining=list(required)
    while remaining:
        key=remaining.pop()
        item=lookup[key]
        if item["visibility"]=="private" and specialist!="context_intelligence":
            raise ContextAccessDenied("Private prerequisite")
        for dep in item["dependencies"]:
            if dep not in required:
                include(dep)
                remaining.append(dep)
    allowed=[lookup[x] for x in sorted(required)]
    if len(_json(allowed).encode("utf-8"))>max_bytes:
        raise ContextBudgetExceeded("Critical goal, metric or caveat exceeds context budget")
    included=set(required)
    omitted=[]
    for key in dict.fromkeys(optional):
        if key in included:
            continue
        item=lookup.get(key)
        if not item or item["visibility"]=="private":
            continue
        closure=set()
        def walk(k):
            if k in included or k in closure:
                return
            part=lookup[k]
            if part["visibility"]=="private":
                raise ContextAccessDenied("Private prerequisite")
            closure.add(k)
            for dep in part["dependencies"]:
                walk(dep)
        try:
            walk(key)
        except ContextAccessDenied:
            continue
        proposed=[lookup[x] for x in sorted(included|closure)]
        if len(_json(proposed).encode("utf-8"))<=max_bytes:
            included|=closure
        else:
            omitted.append(key)
    selected=[lookup[x] for x in sorted(included)]
    return {"schema_version":VERSION,"owner_scope":owner,
            "job_id":job_id,"recipient_specialist":specialist,
            "context_revision":graph["context_revision"],
            "nodes":selected,"content_sha256":_sha(selected),
            "omitted_context":{"count":len(omitted),
                               "available_ids":omitted[:50],
                               "retrievable_via":"context_fetch(ids,purpose,max_bytes)"}}


def affected_dependents(graph: dict,changed_ids: set[str]) -> list[str]:
    """Invalidate only descendants of modified evidence, never unrelated work."""
    validate_fabric(graph)
    lookup={item["id"]:item for item in graph["nodes"]}
    if not changed_ids<=set(lookup):
        raise ContextIntegrityError("Unknown source revision node")
    dependents=defaultdict(set)
    for node_ in graph["nodes"]:
        for dep in node_["dependencies"]:
            dependents[dep].add(node_["id"])
    result=set()
    stack=list(changed_ids)
    while stack:
        src=stack.pop()
        for target in dependents[src]:
            if target not in result:
                result.add(target)
                stack.append(target)
    return sorted(result-changed_ids)


def migrate_v1(ir,*,owner: str,job_id: str,objective: str,
               deliverables: list[str],requirements: list[dict] | None = None,
               dataset_summary: dict | None = None,
               unknowns: list[str] | None = None) -> dict:
    """No promotion of old narrative into independently verified evidence."""
    from .work_outcome_phases import phase_projection
    if not isinstance(objective,str) or not objective.strip():
        raise ContextIntegrityError("Missing original user intent")
    goal_data={"original_objective":objective,
               "authorized_formats":list(deliverables),
               "source_ir_sha256":ir.sha256}
    goal=node(id="goal:original",kind="goal",data=goal_data,status="approved")
    out=[goal]
    for item in (requirements or []):
        out.append(node(id="requirement:"+item["id"],kind="requirement",
                        data={"kind":item["kind"],"obligation":item["obligation"],
                              "evidence_needed":item["evidence_needed"],
                              "priority":item.get("priority",5),
                              "phase":next(row["phase"] for row in
                                   phase_projection([item]) if row["id"]==item["id"])},
                        dependencies=("goal:original",),status="pending"))
    for idx,url in enumerate(ir.sources):
        out.append(node(id="source:"+str(idx),kind="source",
                        data={"url":url,"content_verified":False,
                              "provenance":"provider_attribution_only"},
                        status="attributed"))
    for i,(heading,text) in enumerate(ir.sections):
        # The original report is an unverified candidate; it is not an insight.
        out.append(node(id="narrative_candidate:"+str(i),
                        kind="narrative_candidate",
                        data={"heading":heading,"content":text,
                              "qualification":"unverified_narrative_candidate"},
                        dependencies=("goal:original",),status="candidate"))
    if dataset_summary is not None:
        if (dataset_summary.get("sql_row_count") != dataset_summary.get("rows")
                or ir.dataset_digest is None):
            raise ContextIntegrityError("Dataset row counts or hashes not reconciled")
        receipt=node(id="source:dataset",kind="source",
                     data={"dataset_summary_sha256":ir.dataset_digest,
                           "content_verified":False,
                           "provenance":"independently_computed_summary_only"},
                     status="attributed")
        out.append(receipt)
        for key,metrics in sorted((dataset_summary.get("numeric") or {}).items()):
            if not isinstance(metrics,dict):
                continue
            for statistic in ("count","mean","min","max"):
                value=metrics.get(statistic)
                if type(value) not in (int,float) or not math.isfinite(value):
                    continue
                out.append(node(
                    id="metric:"+str(len([n for n in out if n["kind"]=="metric"])),
                    kind="metric",
                    data={"name":key,"statistic":statistic,
                          "value":value,"unit":"not_declared_by_source",
                          "period":"dataset_scope_unspecified",
                          "dataset_summary_sha256":ir.dataset_digest},
                    dependencies=("source:dataset",),
                    status="computed_summary"))
    for i,unknown in enumerate((unknowns or [])[:30]):
        out.append(node(id="uncertainty:"+str(i),kind="uncertainty",
                        data={"statement":unknown,
                              "impact":"requires explicit disclosure"},
                        dependencies=("goal:original",),status="unknown"))
    # The immutable outcome hash excludes changing source/checkpoint bytes.
    # A source revision may replace the graph without rewriting authorization.
    authorization={"original_objective":objective,
                   "authorized_formats":list(deliverables)}
    return create_fabric(owner=owner,job_id=job_id,
        goal_digest=_sha(authorization),nodes=out)
