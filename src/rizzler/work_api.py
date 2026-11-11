"""Authenticated Work Agent endpoints; bearer identity is separate from voice key."""
from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .work_auth import verify_token
from .identity import Identity
from .work_skills import SKILLS
from .work_store import WorkStore, Conflict, Missing

def router(store: WorkStore, signing_key: str, identity: Identity | None = None) -> APIRouter:
    api=APIRouter(prefix="/api/work",tags=["work"])
    def owner(req: Request):
        if identity is not None:
            return identity.owner(req, mutate=req.method not in ("GET", "HEAD", "OPTIONS"))
        try:
            # Bearer tokens cannot be minted via the public voice-key endpoint.
            return verify_token(req.headers.get("authorization"), signing_key)
        except PermissionError:
            raise HTTPException(status_code=401,detail="Invalid work authorization")

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
                line="The job is "+state+". Last recorded stage: "+stage+"."
            return {"job_id":jid,"status":state,"text":line}
        except Missing:
            raise HTTPException(status_code=404, detail="Job not found")

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

    @api.post("/uploads",status_code=201)
    async def upload(req: Request):
        who=owner(req);same_origin(req)
        raw=bytearray()
        async for chunk in req.stream():
            raw.extend(chunk)
            if len(raw)>8_000_000:
                raise HTTPException(status_code=413,detail="Upload too large")
        try:return store.register_upload(who,req.headers.get("x-file-name",""),bytes(raw))
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
