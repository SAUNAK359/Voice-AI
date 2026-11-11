"""Separate Work Agent worker process. Model text is not a substitute for sources."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import shutil
from pathlib import Path

from .artifacts import verify_artifact
from .contracts import FILE_FORMATS
from .work_store import WorkStore, StaleLease
from .work_skills import SKILLS, FORMATS, read_dataset, analyze, render_one


async def compose_work(objective: str, data_summary: dict | None, *, max_chars=18000) -> str:
    """Dedicated model request, bounded and without access to filesystem/tools."""
    from .config import Settings
    cfg=Settings.from_env()
    if not cfg.gemini_api_key:
        raise RuntimeError("Gemini work model is not configured")
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=cfg.gemini_api_key)
    prompt = ("Produce a professional, clearly organized report using Markdown headings. "
              "Never invent external sources, statistics, user data or tool results. "
              "Express uncertainty and limitations. The following dataset metrics are "
              "computed independently; quote only what they substantiate.\n\n"
              "Objective:\n" + objective[:8000] + "\n\nDataset summary:\n" +
              json.dumps(data_summary or {}, ensure_ascii=False)[:9000])
    try:
        async with asyncio.timeout(min(90, cfg.request_timeout)):
            response=await client.aio.models.generate_content(
                model=cfg.gemini_model, contents=prompt,
                config=types.GenerateContentConfig(temperature=0.25,
                    max_output_tokens=3000))
        result=getattr(response, "text", "") or ""
        if not 15<=len(result.strip())<=max_chars:
            raise ValueError("Model report missing or too long")
        return result
    finally:
        await client.aio.aclose()


async def grounded_research(objective: str) -> tuple[str,list[str]]:
    """Only returns URLs obtained from Gemini provider grounding metadata."""
    from .config import Settings
    cfg=Settings.from_env()
    if not cfg.gemini_api_key: raise RuntimeError("Gemini key is required for grounded research")
    from google import genai
    from google.genai import types
    client=genai.Client(api_key=cfg.gemini_api_key)
    try:
        async with asyncio.timeout(min(90,cfg.request_timeout)):
            response=await client.aio.models.generate_content(
                model=cfg.gemini_model,
                contents=("Research the following objective. Provide dated, attributed "
                          "findings with sources and uncertainty. Never invent citations:\n"+objective[:8000]),
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.2,max_output_tokens=1300))
        urls=[]
        for cand in (getattr(response,"candidates",None) or []):
            meta=getattr(cand,"grounding_metadata",None)
            for chunk in (getattr(meta,"grounding_chunks",None) or []):
                web=getattr(chunk,"web",None)
                uri=getattr(web,"uri",None)
                if isinstance(uri,str) and uri.startswith("https://"):
                    urls.append(uri)
        urls=list(dict.fromkeys(urls))[:30]
        if not urls: raise ValueError("No provider-grounded research sources")
        answer=getattr(response,"text","") or ""
        if len(answer.strip())<40:raise ValueError("Grounded response lacks substantive text")
        return answer,urls
    finally:
        await client.aio.aclose()


class WorkWorker:
    def __init__(self,store:WorkStore, composer=compose_work, researcher=grounded_research):
        self.store,self.composer,self.researcher=store,composer,researcher
        self.identity=secrets.token_hex(12)

    async def once(self) -> bool:
        claim=self.store.claim(self.identity,lease_seconds=45)
        if not claim: return False
        jid,owner,fence=claim["id"],claim["owner"],claim["fence"]
        payload=claim["payload"]
        stage=self.store.root/"staging"/jid/str(fence)
        stage.mkdir(parents=True,exist_ok=True,mode=0o700)
        # Heartbeat protects long model calls against lost ownership.
        async def heartbeat():
            while True:
                await asyncio.sleep(12)
                self.store.renew(jid,self.identity,fence,lease_seconds=45)
        guard=asyncio.create_task(heartbeat())
        try:
            formats=payload["deliverables"]
            uploaded=[self.store.upload(owner,uid) for uid in payload["uploads"]]
            self.store.renew(jid,self.identity,fence,stage="analysis")
            table=None;summary=None
            if uploaded:
                if len(uploaded)>1:
                    raise ValueError("Only one dataset per job is currently supported")
                table=await asyncio.to_thread(read_dataset,uploaded[0])
                summary=await asyncio.to_thread(analyze,*table)
            if "data_analysis" in formats and summary is None:
                raise ValueError("Data analysis requires a dataset")
            if "research" in formats:
                self.store.renew(jid,self.identity,fence,stage="research")
                text,sources=await self.researcher(payload["objective"])
            else:
                self.store.renew(jid,self.identity,fence,stage="planning")
                text=await self.composer(payload["objective"],summary)
                sources=[]
            if "automation_plan" in formats:
                # Deliberately no automatic recurring execution.
                self.store.proposal(owner,jid,1440)
            if summary:
                text += "\n\n## Dataset quality (computed, not model-generated)\n"+json.dumps(summary,indent=2)
            self.store.renew(jid,self.identity,fence,stage="rendering")
            receipts=[]
            for kind in formats:
                if kind=="zip":continue
                if kind not in FORMATS:continue
                path=stage/(kind+"."+kind)
                await asyncio.to_thread(render_one,kind,path,payload["objective"][:120],text,table,sources)
                receipts.append(verify_artifact(path,kind))
                self.store.renew(jid,self.identity,fence,lease_seconds=45)
            if "zip" in formats:
                import zipfile
                zpath=stage/"zip.zip"
                manifest={"schema_version":1,"files":[{"name":r.name,"sha256":r.sha256,
                    "bytes":r.byte_size} for r in receipts]}
                if not receipts:raise ValueError("ZIP requires at least one other requested file")
                with zipfile.ZipFile(zpath,"w",compression=zipfile.ZIP_DEFLATED) as archive:
                    for r in receipts: archive.write(stage/r.name,arcname=r.name)
                    archive.writestr("MANIFEST.json",json.dumps(manifest,indent=2))
                    archive.writestr("README.txt","Rizzler Work Agent verified bundle\n")
                receipts.append(verify_artifact(zpath,"zip"))
            self.store.renew(jid,self.identity,fence,stage="validating")
            self.store.finish(jid,self.identity,fence,text,receipts,stage)
            return True
        except (StaleLease,InterruptedError):
            self.store.fail(jid,self.identity,fence,"cancelled_or_stale")
        except Exception:
            # Never return exception strings that could include prompts, keys or PII.
            self.store.fail(jid,self.identity,fence,"execution_error")
        finally:
            guard.cancel()
            await asyncio.gather(guard,return_exceptions=True)
            shutil.rmtree(stage,ignore_errors=True)
        return True


async def serve(store,interval=1):
    worker=WorkWorker(store)
    while True:
        store.schedule_due()
        if not await worker.once():
            await asyncio.sleep(interval)


def main():
    p=argparse.ArgumentParser(description="Durable Rizzler Work Agent worker")
    p.add_argument("--root",default=os.environ.get("RIZZLER_WORK_ROOT",""))
    p.add_argument("--once",action="store_true")
    args=p.parse_args()
    if not args.root: p.error("Set --root on a persistent disk")
    store=WorkStore(args.root)
    asyncio.run(WorkWorker(store).once() if args.once else serve(store))


if __name__=="__main__":
    main()
