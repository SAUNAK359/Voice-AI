"""Explicitly untrusted V25 narrative -> typed V26 context adapter.

No source URL or arbitrary report paragraph becomes a verified fact.
Only executed SQL/profile receipts can be promoted to verified computed
metrics; units remain unspecified unless the source data explicitly says so.
"""
from __future__ import annotations

from .work_context_fabric import new_graph,commit_nodes,digest


def legacy_context_to_fabric(*,owner: str,job_id: str,payload: dict,
                             ir, summary: dict | None,
                             goal_contract: dict | None) -> dict:
    graph=new_graph(owner=owner,job_id=job_id,task=payload)
    nodes=[]
    goal_id="goal:original"
    nodes.append({
        "id":goal_id,"kind":"goal","status":"unknown",
        "statement":payload["objective"][:3500],
        "source_ids":[],"unit":"","scope":{},"critical":True,
        "audience_tags":[],"digest":None})
    requirements=(goal_contract or {}).get("requirements") or []
    for i,req in enumerate(requirements[:30]):
        nodes.append({
            "id":"requirement:"+str(i),
            "kind":"requirement","status":"unknown",
            "statement":str(req.get("obligation") or "Unspecified required outcome")[:3500],
            "source_ids":[],"unit":"",
            "scope":{"note":str(req.get("kind","unknown"))[:100]},
            "critical":int(req.get("priority",0))>=4,
            "audience_tags":[],"digest":None})
    for index,url in enumerate(ir.sources[:24]):
        # The presence of a URL proves NO retrieval, quotation or factual truth.
        nodes.append({
            "id":"source:url_"+str(index),"kind":"source",
            "status":"provider_attributed","statement":url,
            "source_ids":[],"unit":"",
            "scope":{"source_method":"provider_attribution_only"},
            "critical":False,"audience_tags":[],"digest":None})
    if isinstance(summary,dict) and isinstance(summary.get("numeric"),dict):
        receipt="source:dataset_"+str(ir.dataset_digest or "unknown")[:55]
        for field,stats in list(summary["numeric"].items())[:32]:
            if not isinstance(stats,dict):
                continue
            for label in ("count","min","max","mean"):
                raw=stats.get(label)
                if type(raw) not in (int,float):
                    continue
                from math import isfinite
                if not isfinite(raw):
                    continue
                nodes.append({
                    "id":"metric:"+str(len(nodes)),
                    "kind":"metric","status":"computed_verified",
                    "statement":str(field) + " " + label + " = " + str(raw),
                    "source_ids":[receipt],
                    "unit":"unspecified_source_unit",
                    "scope":{"dimension":str(field)[:130],
                             "source_method":"independent_dataset_profile",
                             "note":"source digest: "+str(ir.dataset_digest)[:80]},
                    "critical":False,"audience_tags":[],"digest":ir.dataset_digest})
    # Dataset and source caveats must not disappear across role-specific views.
    if ir.sources:
        nodes.append({
            "id":"uncertainty:source_attribution",
            "kind":"uncertainty","status":"analysis",
            "statement":"A source URL or provider attribution does not establish independently verified factual text.",
            "source_ids":[],"unit":"","scope":{},"critical":True,
            "audience_tags":[],"digest":None})
    if summary is not None:
        nodes.append({
            "id":"uncertainty:units",
            "kind":"uncertainty","status":"analysis",
            "statement":"Numerical units and time/geography scopes must be established from the source dataset before interpreting metrics.",
            "source_ids":[],"unit":"","scope":{},"critical":True,
            "audience_tags":[],"digest":None})
    return commit_nodes(graph,nodes=nodes,
                        owner=owner,job_id=job_id,
                        base_revision=graph["revision"])
