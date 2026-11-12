"""Evidence provenance for provider-grounded search, without arbitrary URL fetching.

Search results are untrusted source material. HTTPS links are not factual proof.
No direct page fetch means attacker-controlled redirects cannot trigger SSRF.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import time
from urllib.parse import urlsplit, urlunsplit

BLOCKED = {"localhost", "metadata.google.internal", "metadata", "host.docker.internal"}
PRIVATE_ENDINGS = (".local", ".localhost", ".internal", ".onion", ".test", ".invalid")


def safe_source_url(raw: str) -> str | None:
    if not isinstance(raw, str) or len(raw) > 2048 or any(ord(c) < 32 for c in raw):
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
        name=parsed.hostname.rstrip(".").lower()
        if name in BLOCKED or name.endswith(PRIVATE_ENDINGS) or "." not in name:
            return None
        if not re.fullmatch(r"[a-z0-9.-]+", name) or ".." in name:
            return None
        try:
            ipaddress.ip_address(name)
            return None  # Do not accept bare IP addresses as evidence sources.
        except ValueError:
            pass
        if parsed.port not in (None, 443):
            return None
        return urlunsplit(("https",name,parsed.path or "/",parsed.query,""))
    except (ValueError,UnicodeError):
        return None


def source_records(response, *, at: float | None = None) -> list[dict]:
    timestamp = time.time() if at is None else at
    records, seen = [], set()
    for candidate in (getattr(response, "candidates", None) or []):
        meta = getattr(candidate,"grounding_metadata",None)
        for item in (getattr(meta,"grounding_chunks",None) or []):
            web=getattr(item,"web",None)
            url=safe_source_url(getattr(web,"uri",None))
            if not url or url in seen:
                continue
            seen.add(url)
            title=getattr(web,"title","") or ""
            title=re.sub(r"\s+"," ",title).strip()[:180]
            records.append({"id":hashlib.sha256(url.encode()).hexdigest()[:16],
                            "url":url,"publisher":urlsplit(url).hostname,
                            "title":title, "retrieved_at":timestamp,
                            "attribution":"provider_grounding",
                            "content_verified":False,
                            "published_at":None})
            if len(records)>=24:return records
    return records


def evidence_summary(records: list[dict]) -> dict:
    """Describe actual evidence coverage without promoting it to factual proof."""
    hosts={rec["publisher"] for rec in records}
    return {"sources":len(records),"publishers":len(hosts),
            "provenance":"Gemini search grounding",
            "citation_verification":"provider_attribution_only",
            "source_document_fetch":False,
            "freshness_verified":False}
