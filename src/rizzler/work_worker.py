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
    from .work_agents import read_skill
    client=genai.Client(api_key=cfg.gemini_api_key)
    try:
        async with asyncio.timeout(min(90,cfg.request_timeout)):
            response=await client.aio.models.generate_content(
                model=cfg.gemini_model,
                contents=("Research the following objective. Provide dated, attributed "
                          "findings with sources and uncertainty. Never invent citations:\n"+objective[:8000]),
                config=types.GenerateContentConfig(
                    system_instruction=read_skill("research")[:6500],
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
        claim = self.store.claim(self.identity, lease_seconds=45)
        if not claim:
            return False
        jid, fence = claim["id"], claim["fence"]
        # The WorkStore is authoritative for all specialist progress and
        # checkpoint transitions; Voice turns remain independent of these jobs.
        async def heartbeat():
            while True:
                await asyncio.sleep(12)
                self.store.renew(jid, self.identity, fence, lease_seconds=45)
        guard = asyncio.create_task(heartbeat(), name="work-lease-heartbeat")
        try:
            from .work_specialists import execute_specialists
            await execute_specialists(
                self.store, claim, self.identity, self.composer, self.researcher)
        except (StaleLease, InterruptedError):
            self.store.fail(jid, self.identity, fence, "cancelled_or_stale")
        except asyncio.CancelledError:
            # Never silently mark a interrupted worker's job as successful.
            self.store.fail(jid, self.identity, fence, "worker_interrupted")
            raise
        except Exception:
            # Error strings could include user prompts and provider secrets.
            self.store.fail(jid, self.identity, fence, "execution_error")
        finally:
            guard.cancel()
            await asyncio.gather(guard, return_exceptions=True)
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
    from .work_objects import from_environment
    objects = from_environment()
    if os.environ.get("RIZZLER_DATABASE_URL"):
        from .work_postgres import PostgresWorkStore
        store=PostgresWorkStore(args.root,os.environ["RIZZLER_DATABASE_URL"],object_store=objects)
    else:
        store=WorkStore(args.root,object_store=objects)
    asyncio.run(WorkWorker(store).once() if args.once else serve(store))


if __name__=="__main__":
    main()
