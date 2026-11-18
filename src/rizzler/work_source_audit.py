"""Bounded audited source acquisition for externally permitted Work research.

A provider-grounded URL does not prove any associated claim. This stage
fetches actual public-HTTPS source content using the existing DNS-pinned,
TLS-verified SSRF-resistant downloader and records the precise original text
available for later model review and numerical cell provenance.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Any


async def audit_source_records(records: list[dict], *,
                               limit: int | None = None,
                               reader=None) -> dict[str,Any]:
    from .research_evidence import safe_source_url
    from .work_searxng import _read_page

    if not isinstance(records,list) or len(records)>24:
        raise ValueError("Unbounded provider grounding records")
    if limit is None:
        raw=os.environ.get("RIZZLER_HACE_SOURCE_FETCH_LIMIT","8")
        if not raw.isdecimal() or not 1 <= int(raw) <= 12:
            raise ValueError("Source audit URL budget must be 1..12")
        limit=int(raw)
    if not 1<=limit<=12:
        raise ValueError("Source audit limit invalid")
    if reader is None:
        reader=_read_page
    urls=[]
    for record in records:
        if not isinstance(record,dict):
            continue
        url=record.get("url")
        if (isinstance(url,str) and safe_source_url(url)==url
                and url not in urls):
            urls.append(url)
        if len(urls)>=limit:break
    semaphore=asyncio.Semaphore(min(5,len(urls) or 1))

    async def fetch(url):
        async with semaphore:
            try:
                item=await asyncio.wait_for(
                    asyncio.to_thread(reader,url),timeout=24)
                if item is None:return None
                resolved,text=item
                if not isinstance(text,str) or len(text)<100:
                    return None
                if not isinstance(resolved,str) or safe_source_url(resolved)!=resolved:
                    return None
                content=text[:6500]
                return {"url":url,"final_url":resolved,"excerpt":content,
                        "content_sha256":hashlib.sha256(
                            content.encode("utf-8")).hexdigest(),
                        "attribution":"direct_public_https_fetch",
                        "content_fetched":True,
                        "claim_verified":False}
            except (ValueError,RuntimeError,TimeoutError,OSError,
                    ImportError,asyncio.TimeoutError):
                return None
    results=await asyncio.gather(*(fetch(url) for url in urls))
    passages=[item for item in results if item is not None]
    return {"attempted":len(urls),"fetched":len(passages),
            "evidence_passages":passages,
            "claim_verification":"not_performed",
            "limits":"Fetch confirms page content only; claim entailment must be reviewed separately"}
