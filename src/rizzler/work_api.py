"""Work endpoints share the single authenticated Voice/Work owner session."""
from __future__ import annotations
import json
import hashlib
import sqlite3
import zipfile
import asyncio
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .identity import Identity
from .work_skills import SKILLS
from .work_agents import SPECS
from .work_store import WorkStore, Conflict, Missing
from .upload_scan import ScanUnavailable

def router(store: WorkStore, identity: Identity | None = None,
           owner_admission=None, owner_resolver=None) -> APIRouter:
    """No separate Work login or bearer credential; request owner is shared."""
    api=APIRouter(prefix="/api/work",tags=["work"])
    def owner(req: Request):
        if owner_resolver is not None:
            return owner_resolver(req)
        if identity is None:
            raise HTTPException(status_code=503,detail="Shared authentication not configured")
        subject=identity.owner(req,mutate=req.method not in ("GET","HEAD","OPTIONS"))
        if owner_admission is not None:
            from .owner_admission import classify, RateExceeded
            try:owner_admission.admit(subject,classify(req.method,req.url.path))
            except RateExceeded as exc:
                raise HTTPException(status_code=429,detail="Request rate exceeded",
                    headers={"Retry-After":str(exc.retry_after)}) from None
        return subject

    def same_origin(req: Request):
        if identity is not None:
            return  # Strict origin and CSRF validated by identity.owner(mutate=True).
        origin=req.headers.get("origin")
        if origin:
            parsed=urlparse(origin)
            if parsed.scheme not in ("http","https") or parsed.netloc!=req.headers.get("host"):
                raise HTTPException(status_code=403,detail="Cross-origin request refused")

    @api.get("/skills")
    def skills(req: Request):
        owner(req)
        return {"skills":[{"name":n,"description":d} for n,d in SKILLS.items()],
                "supported": "Registered capability; live behavior depends on configured providers and format dependencies"}

    @api.post("/jobs",status_code=202)
    async def submit(req: Request):
        who=owner(req);same_origin(req)
        try:
            raw=await req.body()
            if len(raw)>15000: raise ValueError("Request too large")
            data=json.loads(raw)
            if not isinstance(data,dict): raise ValueError("Invalid job document")
            objective, formats=data.get("objective"),data.get("deliverables")
            uploads=data.get("uploads",[])
            if not isinstance(objective,str):raise ValueError("Objective must be text")
            return store.submit(who,objective,formats,
                req.headers.get("idempotency-key",""),uploads)
        except (ValueError,TypeError,UnicodeDecodeError,json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400,detail="Invalid job request") from None
        except Conflict:
            raise HTTPException(status_code=409,detail="Conflicting idempotency key")
        except Missing:
            raise HTTPException(status_code=404,detail="Upload not found")

    @api.get("/jobs")
    def jobs(req: Request):
        return {"jobs":store.list_jobs(owner(req))}

    @api.get("/jobs/{jid}")
    def job(req: Request,jid: str):
        try:return store.get(owner(req),jid)
        except Missing:raise HTTPException(status_code=404,detail="Job not found")

    @api.get("/jobs/{jid}/plan")
    def job_plan(req: Request, jid: str):
        try:
            return store.job_plan(owner(req),jid)
        except Missing:
            raise HTTPException(status_code=404,detail="Job not found") from None
        except ValueError:
            raise HTTPException(status_code=503,detail="Work plan integrity unavailable") from None

    @api.get("/jobs/{jid}/agents")
    def agent_statuses(req: Request, jid: str):
        who = owner(req)
        try:
            parent = store.get(who, jid)
            steps = store.agent_steps(who, jid)
        except Missing:
            raise HTTPException(status_code=404, detail="Job not found") from None
        now = __import__("time").time()
        for step in steps:
            if parent["status"] in ("cancelled", "failed") and step["status"] == "queued":
                step["status"] = "not_executed"
            deadline = step.pop("deadline")
            finished = step["finished"]
            step["target_seconds"] = SPECS[step["agent"]].sla_seconds
            step["elapsed_seconds"] = round(max(0, (
                finished if finished > 0 else now) - step["started"]), 2
            ) if step["started"] > 0 else None
            if step["status"] == "completed":
                step["sla"] = "met" if finished <= deadline else "breached"
            elif step["status"] == "running":
                step["sla"] = "overdue" if now > deadline else "within_target"
            else:
                step["sla"] = "not_applicable"
            step["target_deadline"] = deadline
            try:
                step["quality"] = json.loads(step.pop("qa_json")) if step.get("qa_json") else None
            except ValueError:
                step["quality"] = None
            step.pop("qa_json", None)
        return {"job_id": jid, "agents": steps,
                "sla_definition": "Best-effort stage target, not a contractual guarantee"}

    @api.get("/jobs/{jid}/quality")
    def job_quality(req: Request, jid: str):
        try:
            return store.quality_report(owner(req), jid)
        except Missing:
            raise HTTPException(status_code=404, detail="Job not found") from None
        except ValueError:
            raise HTTPException(status_code=503, detail="Quality evidence unavailable") from None

    @api.get("/jobs/{jid}/voice-status")
    def voice_status(req: Request, jid: str):
        try:
            who=owner(req)
            j=store.get(who,jid)
            events=store.events(who,jid)
            stage=events[-1]["stage"] if events else j["stage"]
            state=j["status"]
            if state=="completed":
                count=len(store.artifacts(who,jid))
                line=f"Work completed. {count} verified downloadable artifacts are ready."
            elif state=="failed":
                line="The job failed. The recorded error status is "+j["error_code"]+"."
            elif state=="cancelled":
                line="The job was cancelled. No completed deliverables are claimed."
            elif j["cancel_requested"]:
                line="Cancellation is pending. The worker has not acknowledged it yet."
            else:
                steps=store.agent_steps(who,jid)
                done=sum(step["status"]=="completed" for step in steps)
                running=[step["agent"].replace("_"," ") for step in steps
                         if step["status"]=="running"]
                line=f"{done} of {len(steps)} specialist stages completed."
                if running:
                    line+=" Working now: "+", ".join(running[:2])+"."
                else:
                    line+=" Job is "+state+"."
            return {"job_id":jid,"status":state,"text":line}
        except Missing:
            raise HTTPException(status_code=404, detail="Job not found")

    @api.get("/jobs/{jid}/specification")
    def job_specification(req: Request,jid: str):
        try:return store.specification(owner(req),jid)
        except Missing:
            raise HTTPException(status_code=404,detail="Job not found") from None

    @api.get("/jobs/{jid}/lineage")
    def job_lineage(req: Request,jid: str):
        try:return store.lineage(owner(req),jid)
        except Missing:
            raise HTTPException(status_code=404,detail="Job not found") from None

    @api.post("/jobs/{jid}/revisions",status_code=202)
    async def propose_revision(req: Request,jid: str):
        who=owner(req);same_origin(req)
        raw=await req.body()
        if len(raw)>11500:
            raise HTTPException(status_code=413,detail="Revision too large")
        try:
            data=json.loads(raw)
            if not isinstance(data,dict) or set(data)!={"objective","deliverables"}:
                raise ValueError()
            return store.prepare_agent_action(who,"work.revise",
                {"job_id":jid,**data})
        except Missing:
            raise HTTPException(status_code=404,detail="Job not found") from None
        except (ValueError,TypeError):
            raise HTTPException(status_code=400,detail="Invalid revision") from None
        except Conflict:
            raise HTTPException(status_code=409,detail="Revision unavailable") from None

    @api.post("/jobs/{jid}/retry",status_code=202)
    def propose_retry(req: Request,jid: str):
        who=owner(req);same_origin(req)
        try:return store.prepare_agent_action(who,"work.retry",{"job_id":jid})
        except Missing:
            raise HTTPException(status_code=404,detail="Job not found") from None
        except Conflict:
            raise HTTPException(status_code=409,detail="Retry unavailable") from None

    @api.post("/agent/approvals/{approval_id}/confirm")
    def approve_agent_action(req: Request,approval_id: str):
        who=owner(req);same_origin(req)
        try:return {"confirmed":True,"job":store.confirm_agent_action(who,approval_id)}
        except Missing:
            raise HTTPException(status_code=404,detail="Approval unavailable") from None
        except (Conflict,ValueError):
            raise HTTPException(status_code=409,detail="Confirmation invalid or expired") from None

    @api.get("/jobs/{jid}/events")
    def events(req: Request,jid: str,after: int=0):
        if after<0:raise HTTPException(status_code=400,detail="Invalid sequence")
        try:return {"events":store.events(owner(req),jid,after)}
        except Missing:raise HTTPException(status_code=404,detail="Job not found")

    @api.post("/jobs/{jid}/cancel")
    def cancel(req: Request,jid: str):
        who=owner(req);same_origin(req)
        try:return store.cancel(who,jid)
        except Missing:raise HTTPException(status_code=404,detail="Job not found")

    @api.get("/jobs/{jid}/artifacts")
    def artifacts(req: Request,jid: str):
        try:return {"artifacts":store.artifacts(owner(req),jid)}
        except Missing:raise HTTPException(status_code=404,detail="Job not found")

    @api.get("/artifacts/{aid}")
    def download(req: Request,aid: str):
        try:
            path,info=store.artifact(owner(req),aid)
            return FileResponse(path,filename=info["name"],headers={
                "Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})
        except Missing:raise HTTPException(status_code=404,detail="Artifact unavailable")

    # V13 source intake: indexed passages are not raw context pasted into prompts.
    # The source index is owner-scoped and shares the existing Work storage root.
    @api.get("/artifacts/{aid}/preview")
    def preview_artifact(req: Request,aid: str):
        from .artifact_preview import render
        try:
            path,meta=store.artifact(owner(req),aid)
            return render(path,meta["kind"])
        except Missing:
            raise HTTPException(status_code=404,detail="Artifact unavailable") from None
        except (ValueError,OSError,zipfile.BadZipFile):
            raise HTTPException(status_code=422,detail="Safe structured preview unavailable") from None

    @api.post("/sources/url",status_code=201)
    async def source_url_upload(req: Request):
        who=owner(req);same_origin(req)
        from .source_links import download
        from .source_index import SourceIndex
        try:
            raw=await req.body()
            if len(raw)>2400:raise ValueError("URL request too large")
            data=json.loads(raw)
            if type(data) is not dict or set(data)!={"url"} or type(data["url"]) is not str:
                raise ValueError("Invalid URL request")
            result=await asyncio.wait_for(asyncio.to_thread(download,data["url"]),timeout=26)
            name="web_"+hashlib.sha256(result["url"].encode()).hexdigest()[:16]+result["extension"]
            if store.upload_scanner is not None:
                await asyncio.to_thread(store.upload_scanner,result["data"])
            item=await asyncio.to_thread(SourceIndex(store.root).register,
                                          who,name,result["data"],result["url"])
            return {**item,"url":result["url"],"content_type":result["content_type"]}
        except (ValueError,UnicodeError,TimeoutError,asyncio.TimeoutError,json.JSONDecodeError):
            raise HTTPException(status_code=422,detail="Unable to safely retrieve or index public HTTPS source") from None
        except ScanUnavailable:
            raise HTTPException(status_code=503,detail="Source scanner unavailable") from None

    @api.post("/sources",status_code=201)
    async def source_upload(req: Request):
        who=owner(req);same_origin(req)
        from .source_index import SourceIndex, MAX_BYTES
        raw=bytearray()
        async for part in req.stream():
            raw.extend(part)
            if len(raw)>MAX_BYTES:
                raise HTTPException(status_code=413,detail="Source exceeds 8 MB limit")
        try:
            if store.upload_scanner is not None:
                await asyncio.to_thread(store.upload_scanner,bytes(raw))
            return await asyncio.to_thread(SourceIndex(store.root).register,
                    who,req.headers.get("x-file-name",""),bytes(raw))
        except ScanUnavailable:
            raise HTTPException(status_code=503,detail="Source scanner unavailable") from None
        except (ValueError,UnicodeError,sqlite3.DatabaseError):
            raise HTTPException(status_code=400,detail="Invalid or unsupported source") from None

    @api.get("/sources")
    def sources(req: Request):
        from .source_index import SourceIndex
        return {"sources":SourceIndex(store.root).list(owner(req))}

    @api.post("/sources/search")
    async def sources_search(req: Request):
        from .source_index import SourceIndex
        who=owner(req);same_origin(req)
        try:
            raw=await req.body()
            if len(raw)>3000:raise ValueError()
            data=json.loads(raw)
            if set(data)!={"ids","query"} or not isinstance(data["ids"],list) or not isinstance(data["query"],str):
                raise ValueError()
            return await asyncio.to_thread(SourceIndex(store.root).search,who,
                data["ids"],data["query"])
        except (ValueError,TypeError):
            raise HTTPException(status_code=400,detail="Invalid source search") from None
        except PermissionError:
            raise HTTPException(status_code=404,detail="Source not found") from None

    @api.post("/uploads",status_code=201)
    async def upload(req: Request):
        who=owner(req);same_origin(req)
        raw=bytearray()
        async for chunk in req.stream():
            raw.extend(chunk)
            if len(raw)>8_000_000:
                raise HTTPException(status_code=413,detail="Upload too large")
        try:
            return await asyncio.to_thread(
                store.register_upload, who, req.headers.get("x-file-name",""), bytes(raw))
        except ScanUnavailable:
            raise HTTPException(status_code=503,detail="Upload rejected or scanner unavailable") from None
        except Conflict:
            raise HTTPException(status_code=429,detail="Upload quota exceeded")
        except (ValueError,UnicodeError):
            raise HTTPException(status_code=400,detail="Invalid upload") from None

    @api.post("/jobs/{jid}/automation-proposals")
    async def propose(req: Request,jid: str):
        who=owner(req);same_origin(req)
        try:
            raw=await req.body()
            if len(raw)>1024:raise ValueError("Proposal too large")
            values=json.loads(raw)
            return store.proposal(who,jid,values["cadence_minutes"],values.get("max_runs",10))
        except Missing:
            raise HTTPException(status_code=404,detail="Job not found")
        except Conflict:
            raise HTTPException(status_code=409,detail="Complete and verify job before scheduling")
        except (KeyError,ValueError,TypeError):
            raise HTTPException(status_code=400,detail="Invalid proposal")

    @api.get("/automation-proposals")
    def proposals(req: Request):
        return {"proposals":store.list_proposals(owner(req))}

    @api.post("/automation-proposals/{pid}/disable")
    def disable(req: Request,pid: str):
        who=owner(req);same_origin(req)
        try:return store.disable_proposal(who,pid)
        except Missing:raise HTTPException(status_code=404,detail="Proposal not found")
        except Conflict:raise HTTPException(status_code=409,detail="Proposal no longer editable")

    @api.post("/automation-proposals/{pid}/approve")
    def approve(req: Request,pid: str):
        who=owner(req);same_origin(req)
        try:return store.approve_proposal(who,pid)
        except Missing:raise HTTPException(status_code=404,detail="Proposal not found")
        except Conflict:raise HTTPException(status_code=409,detail="Proposal already reviewed")

    return api
