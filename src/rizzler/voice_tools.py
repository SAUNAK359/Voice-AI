"""Voice-facing, authenticated specialist tools. The voice model never supplies owner IDs."""
from __future__ import annotations

import asyncio
import hashlib
import re
import time

from .math_engine import solve_equations

SEARCH_INTENT = re.compile(r"\b(?:search(?: the)? web|web search|look (?:up|online)|browse|research online|current (?:stock price|share price|news|exchange rate)|latest (?:news|price|updates)|(?:stock|share) price (?:of|for)|today['’]?s? (?:news|price|weather))\b", re.I)
WORK_INTENT = re.compile(r"\b(?:make|create|prepare|generate|build|produce|draft|analy[sz]e)\b", re.I)
OUTPUT_INTENT = re.compile(r"\b(?:report|research report|powerpoint|presentation|slides?|excel|spreadsheet|workbook|word document|docx|pdf|csv|data analysis|dataset)\b", re.I)
STATUS_INTENT = re.compile(r"\b(?:status|progress|how(?:'s| is) (?:the|my) (?:job|task|report)|is (?:the|my) (?:report|presentation|job|task) (?:ready|done)|what(?:'s| is) (?:happening|running))\b", re.I)
CANCEL_INTENT = re.compile(r"\b(?:cancel|stop|abort) (?:the |my |that |current |last )?(?:work|job|task|report|analysis|presentation)\b", re.I)


def classify_tool(text: str, have_work: bool) -> str | None:
    if len(text)>8000:return None
    lower=text.casefold().strip()
    if STATUS_INTENT.search(lower) and have_work:return "work_status"
    if CANCEL_INTENT.search(lower) and have_work:return "work_cancel"
    if WORK_INTENT.search(lower) and OUTPUT_INTENT.search(lower) and have_work:return "work_submit"
    if SEARCH_INTENT.search(lower):return "web_search"
    if re.search(r"\b(?:equations?|solve(?: the)? (?:system|problem)|value of a and b)\b",lower) and ("=" in lower or "equal" in lower):
        return "math"
    return None


def requested_formats(text: str) -> list[str]:
    t=text.casefold()
    formats=[]
    mapping=[("pptx",r"\b(?:powerpoint|presentation|slides?|pptx)\b"),
             ("docx",r"\b(?:word (?:report|document|file)|docx)\b"),
             ("xlsx",r"\b(?:excel|spreadsheet|workbook|xlsx)\b"),
             ("pdf",r"\bpdf\b"),("csv",r"\bcsv\b"),
             ("png",r"\b(?:png|chart|visualization)\b"),
             ("md",r"\bmarkdown\b")]
    for kind,pattern in mapping:
        if re.search(pattern,t):formats.append(kind)
    if not formats and re.search(r"\b(?:report|research|analysis)\b",t):formats=["pdf"]
    return formats


async def grounded_search(query: str, settings) -> dict:
    """One bounded live Gemini search request; never synthesize unsourced live data."""
    if not settings.gemini_api_key:
        return {"text":"Live search is unavailable: Gemini API access is not configured.",
                "spoken":"Live search is unavailable because the search provider is not configured.",
                "sources":[],"verified":False}
    from google import genai
    from google.genai import types
    client=genai.Client(api_key=settings.gemini_api_key)
    try:
        async with asyncio.timeout(min(settings.request_timeout,22)):
            response=await client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=("Search for and answer this question with current source evidence. "
                          "Be concise and distinguish current vs historical data. "
                          "For financial prices, state the currency and quote timestamp when available; "
                          "if not available say real-time quote unverified. "
                          "Do not invent citations, data, URLs or verification.\nQuestion: "+query[:1200]),
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.1,max_output_tokens=450))
        urls=[]
        for candidate in getattr(response,"candidates",[]) or []:
            meta=getattr(candidate,"grounding_metadata",None)
            for chunk in getattr(meta,"grounding_chunks",[]) or []:
                web=getattr(chunk,"web",None)
                url=getattr(web,"uri",None)
                if isinstance(url,str) and url.startswith("https://") and len(url)<=2048:
                    urls.append(url)
        urls=list(dict.fromkeys(urls))[:8]
        answer=(getattr(response,"text","") or "").strip()
        if not urls or not answer:
            return {"text":"I couldn't verify that information from grounded live sources. I won't guess.",
                    "spoken":"I couldn't verify that from live sources, so I won't guess.",
                    "sources":[],"verified":False}
        return {"text":answer+"\n\n**Sources:**\n" +"\n".join("- "+url for url in urls),
                "spoken":re.sub(r"\[[^]]+\]\([^)]*\)|https?://\S+|\*","",answer)[:850],
                "sources":urls,"verified":True}
    except (TimeoutError,Exception):
        return {"text":"Live search is temporarily unavailable. No current data has been verified.",
                "spoken":"Live search is temporarily unavailable, so I can't verify current data.",
                "sources":[],"verified":False}
    finally:
        await client.aio.aclose()


class VoiceTools:
    def __init__(self,store,settings):
        self.store,self.settings=store,settings

    async def execute(self,text:str,owner:str,sequence:int=0,uploads: list[str] | None = None)->dict|None:
        intent=classify_tool(text,self.store is not None)
        if not intent:return None
        started=time.perf_counter()
        if intent=="web_search" and re.search(r"\\b(?:can you|do you|have you|are you able|access to|search tools|web search tools)\\b",text,re.I) and not re.search(r"\\b(?:current|latest|today|look up|search for|stock price|share price)\\b",text,re.I):
            ready=bool(self.settings.gemini_api_key)
            return {"tool":"web_search",
                    "text":("I can search live sources when the Gemini grounding service is available. Ask me what to look up." if ready
                            else "The search tool is installed, but its Gemini API key has not been configured."),
                    "spoken":("Yes, I can search current sources. What would you like me to look up?" if ready
                              else "Search is installed, but the provider is not configured."),
                    "verified":ready,"tool_elapsed_ms":0}
        if intent=="math":
            try:
                result=await asyncio.wait_for(asyncio.to_thread(solve_equations,text),timeout=6)
                if result is None:
                    result={"tool":"symbolic_math",
                            "text":"I couldn't parse both equations safely. Please type them as two equations, for example a+b=sqrt(7) and b^2=3/a.",
                            "spoken":"I couldn't parse both equations clearly. Please type them and I'll verify the solution.",
                            "verified":False}
                else:
                    result["tool"]="symbolic_math"
                    result["verified"]=True
            except Exception:
                result={"tool":"symbolic_math","text":"I couldn't verify a solution to those equations. Please send them in written mathematical form.",
                        "spoken":"I couldn't verify the equations. Please type them so I can solve them precisely.","verified":False}
        elif intent=="web_search":
            result=await grounded_search(text,self.settings)
            result["tool"]="web_search"
        elif intent=="work_submit":
            formats=requested_formats(text)
            if not formats:
                return None
            data_needed=bool(re.search(r"\b(?:my |attached |uploaded |this )?(?:spreadsheet|csv|dataset|excel file)\b",text,re.I))
            if data_needed and not uploads:
                return {"tool":"work_submit","text":"Attach the CSV or XLSX dataset in this conversation first. I won't invent input data.",
                        "spoken":"Please attach the dataset in this conversation before I analyze it.",
                        "verified":False}
            idem=hashlib.sha256((owner+"|"+str(sequence)+"|"+text).encode()).hexdigest()[:48]
            try:
                job=await asyncio.to_thread(self.store.submit,owner,text,formats,idem,(uploads or [])[:1] if data_needed else [])
                result={"tool":"work_submit","text":("**Work queued** · "+job["id"]+"\n\nRequested: "+", ".join(formats)+
                                  ". I'll keep this job running independently of the conversation."),
                        "spoken":"Your work is queued. You can keep talking while I work on it.",
                        "verified":True,"job":job}
            except Exception:
                result={"tool":"work_submit","text":"The Work Agent couldn't accept this task. Nothing has been queued.",
                        "spoken":"The task wasn't accepted. I haven't started any background work.",
                        "verified":False}
        else:
            jobs=await asyncio.to_thread(self.store.list_jobs,owner)
            if not jobs:
                result={"tool":intent,"text":"There are no recorded Work Agent jobs for this session.",
                        "spoken":"There are no recorded work jobs for this session.","verified":True}
            else:
                job=jobs[0]
                if intent=="work_cancel":
                    job=await asyncio.to_thread(self.store.cancel,owner,job["id"])
                    line="Cancellation recorded." if job["status"]=="cancelled" else "Cancellation requested; the worker has not acknowledged it yet."
                else:
                    steps=await asyncio.to_thread(self.store.agent_steps,owner,job["id"])
                    completed=sum(s["status"]=="completed" for s in steps)
                    active=", ".join(s["agent"].replace("_"," ") for s in steps if s["status"]=="running")
                    line=(f"Job {job['status']}. {completed} of {len(steps)} stages completed."+
                          (f" Working: {active}." if active else ""))
                    if job["status"]=="completed":
                        files=await asyncio.to_thread(self.store.artifacts,owner,job["id"])
                        line+=f" {len(files)} verified downloadable artifacts."
                result={"tool":intent,"text":line,"spoken":line,"verified":True,"job":job}
        result["tool_elapsed_ms"]=round((time.perf_counter()-started)*1000,2)
        return result
