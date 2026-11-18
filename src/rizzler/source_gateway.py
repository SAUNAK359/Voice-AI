"""HTTPS-only evidence acquisition with DNS-pinned public-address enforcement.

This gateway must run in a restricted egress environment in production.
URLs and redirects are untrusted, no cookies/credentials/proxies are accepted,
and DNS results are checked AT connector resolution time to resist rebinding.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin

from .research_evidence import safe_source_url
from .source_normalizer import MAX_SOURCE_BYTES, normalize_source

MIME_TYPES = frozenset({
    "text/html", "application/xhtml+xml", "text/plain", "text/markdown",
    "text/x-markdown", "application/pdf", "text/csv", "application/csv",
    "application/json", "application/ld+json",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
})


def require_public_ip(value: str) -> str:
    address = ipaddress.ip_address(value)
    # is_global excludes private, loopback, link-local, multicast, metadata,
    # reserved/unspecified and other special-use ranges.
    if not address.is_global:
        raise PermissionError("Evidence gateway refuses non-public network addresses")
    return str(address)


def canonical_evidence_url(value: str) -> str:
    url = safe_source_url(value)
    if url is None:
        raise PermissionError("Evidence gateway requires a canonical public HTTPS URL")
    return url


async def fetch_source(url: str, *, source_id: str, timeout: float = 30.0,
                       max_redirects: int = 3, max_bytes: int = MAX_SOURCE_BYTES) -> dict:
    """Read and normalize a remote source with a bounded DNS/redirect policy.

    The returned extraction is NOT factual verification. HTML shells, access
    errors and image-only PDFs may need alternative sources or optional OCR.
    """
    if not 1 <= max_redirects <= 5 or not 1000 <= max_bytes <= MAX_SOURCE_BYTES:
        raise ValueError("Invalid evidence acquisition budget")
    if not 2 <= timeout <= 90:
        raise ValueError("Invalid evidence timeout")
    try:
        import aiohttp
    except ImportError as exc:
        raise RuntimeError("Evidence acquisition requires aiohttp") from exc

    class PublicDNSResolver(aiohttp.abc.AbstractResolver):
        async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
            canonical_evidence_url("https://" + host + "/")
            loop = asyncio.get_running_loop()
            infos = await loop.getaddrinfo(host, port, family=family,
                                           type=socket.SOCK_STREAM)
            safe = []
            for af, socktype, proto, _, address in infos:
                try:
                    verified = require_public_ip(address[0])
                except (ValueError, PermissionError):
                    continue
                safe.append({"hostname":host, "host":verified, "port":port,
                             "family":af, "proto":proto, "flags":socket.AI_NUMERICHOST})
            if not safe:
                raise PermissionError("Evidence source resolved only to unsafe addresses")
            return safe

        async def close(self):
            return None

    current = canonical_evidence_url(url)
    visited = set()
    client_timeout = aiohttp.ClientTimeout(total=timeout, connect=min(timeout, 12))
    connector = aiohttp.TCPConnector(resolver=PublicDNSResolver(),
                                     use_dns_cache=False, ssl=True, limit=3)
    async with aiohttp.ClientSession(connector=connector, timeout=client_timeout,
                                     trust_env=False, cookie_jar=aiohttp.DummyCookieJar(),
                                     headers={"Accept": "text/html,text/markdown,application/pdf,"
                                                        "application/json,text/csv,text/plain",
                                              "User-Agent": "RizzlerResearch/1.0"}) as session:
        for attempt in range(max_redirects + 1):
            if current in visited:
                raise ValueError("Evidence redirect cycle")
            visited.add(current)
            async with session.get(current, allow_redirects=False) as response:
                if response.status in (301, 302, 303, 307, 308):
                    destination = response.headers.get("Location")
                    if not destination or attempt >= max_redirects:
                        raise ValueError("Evidence redirect budget exhausted")
                    current = canonical_evidence_url(urljoin(current, destination))
                    continue
                if response.status != 200:
                    raise RuntimeError("Evidence fetch HTTP status " + str(response.status))
                kind = response.content_type.lower()
                if kind not in MIME_TYPES:
                    raise ValueError("Unsupported remote content type")
                if response.content_length and response.content_length > max_bytes:
                    raise ValueError("Evidence response too large")
                chunks, count = [], 0
                async for part in response.content.iter_chunked(65536):
                    count += len(part)
                    if count > max_bytes:
                        raise ValueError("Evidence body exceeded download limit")
                    chunks.append(part)
                if not chunks:
                    raise ValueError("Evidence server returned no content")
                normalized = normalize_source(
                    b"".join(chunks), kind, source_id=source_id, source_url=current)
                normalized["http_status"] = response.status
                normalized["redirect_count"] = attempt
                normalized["retrieved_bytes"] = count
                if response.charset and response.charset.lower() not in ("utf-8", "utf8"):
                    normalized["warnings"].append("non_utf8_charset_may_reduce_quality")
                return normalized
    raise ValueError("Evidence fetch did not reach a final source")
