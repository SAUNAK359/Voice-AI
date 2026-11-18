"""Claim-level evidence contracts for Work research.

A source quotation is accepted only if it exists in an independently retrieved,
hashed document block (not in provider grounding metadata). This establishes
retrieval provenance, NOT independent factual truth or causal correctness.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def _normal(text: str) -> str:
    return " ".join(text.split()).casefold()


def evidence_index(documents: list[dict], *, max_spans: int = 360) -> dict[str, dict]:
    """Index extractable passages with stable content-addressed source IDs."""
    if not isinstance(documents, list) or len(documents) > 24:
        raise ValueError("Evidence source count exceeds bounds")
    spans: dict[str, dict] = {}
    for doc in documents:
        if not isinstance(doc, dict) or not isinstance(doc.get("blocks"), list):
            raise ValueError("Malformed source document")
        source = doc.get("source_id")
        digest = doc.get("sha256")
        if not isinstance(source, str) or not re.fullmatch("[A-Za-z0-9_-]{1,64}", source):
            raise ValueError("Untrusted source identity")
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("Missing original source checksum")
        for block in doc["blocks"]:
            if len(spans) >= max_spans:
                break
            if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                continue
            passage = " ".join(block["text"].split())
            if len(passage) < 35:
                continue
            reference = hashlib.sha256((source + ":" + digest + ":" +
                     json.dumps(block.get("location", {}), sort_keys=True) +
                     ":" + passage).encode("utf-8")).hexdigest()[:24]
            spans[reference] = {"source_id": source, "source_url": doc.get("source_url"),
                "source_sha256": digest, "text": passage[:6000],
                "location": block.get("location", {}), "passage_sha256":
                hashlib.sha256(passage.encode()).hexdigest()}
    return spans


def validate_claims(document: dict, spans: dict[str, dict]) -> list[dict]:
    """Reject invented citations and unquoted sources.

    A short direct quotation from a retrieved passage is a verifiable link;
    numerical derivations still require a separate calculation verifier.
    """
    if not isinstance(document, dict) or set(document) != {"schema_version", "claims"}:
        raise ValueError("Invalid claim graph")
    if document["schema_version"] != 1 or not isinstance(document["claims"], list):
        raise ValueError("Unsupported claim graph version")
    if not 1 <= len(document["claims"]) <= 48:
        raise ValueError("Claim graph count outside policy")
    accepted: list[dict] = []
    seen: set[str] = set()
    for claim in document["claims"]:
        if not isinstance(claim, dict) or set(claim) != {
                "claim", "evidence_id", "quote", "interpretation", "limitations"}:
            raise ValueError("Unknown claim fields")
        label, eid, quote = claim["claim"], claim["evidence_id"], claim["quote"]
        if not isinstance(label, str) or not 12 <= len(label.strip()) <= 450:
            raise ValueError("Claim must be a substantive statement")
        if not isinstance(eid, str) or eid not in spans:
            raise ValueError("Claim references unavailable evidence")
        if not isinstance(quote, str) or not 10 <= len(quote.strip()) <= 240:
            raise ValueError("Invalid evidence quotation")
        if _normal(quote) not in _normal(spans[eid]["text"]):
            raise ValueError("Claim quotation is absent from retrieved document")
        if type(claim["interpretation"]) is not bool:
            raise ValueError("Inference label must be boolean")
        limitations = claim["limitations"]
        if not isinstance(limitations, str) or len(limitations) > 350:
            raise ValueError("Invalid claim limitations")
        key = hashlib.sha256((label.casefold() + ":" + eid).encode()).hexdigest()[:24]
        if key in seen:
            raise ValueError("Duplicate source-bound assertion")
        seen.add(key)
        accepted.append({"id": key, "claim": label.strip(), "evidence_id": eid,
            "quote": quote.strip(), "interpretation": claim["interpretation"],
            "limitations": limitations, "source_url": spans[eid]["source_url"],
            "source_sha256": spans[eid]["source_sha256"],
            "location": spans[eid]["location"],
            "status": "quoted_source_observation" if not claim["interpretation"]
                      else "interpretation_with_source"})
    return accepted


def evidence_brief(spans: dict[str, dict], *, max_chars: int = 22500) -> str:
    """Bounded high-signal excerpts for expert claim extraction."""
    result = []
    for eid, item in spans.items():
        entry = {"id": eid, "source": item["source_url"],
                 "location": item["location"], "text": item["text"][:1400]}
        serialized = json.dumps(entry, ensure_ascii=False)
        if sum(len(x) for x in result) + len(serialized) > max_chars:
            break
        result.append(serialized)
    return "\n".join(result)


def claim_summary(claims: list[dict], *, max_chars: int = 15000) -> str:
    return "\n".join(
        "- " + claim["claim"] + " [" + claim["evidence_id"] + "]" +
        (" (interpretation)" if claim["interpretation"] else "") +
        (" Limit: " + claim["limitations"] if claim["limitations"] else "")
        for claim in claims)[:max_chars]
