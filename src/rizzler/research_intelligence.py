"""Bounded model-directed evidence ranking and objective coverage.

Models may recommend source order and relevant findings; independently
downloaded source bytes and exact quotation validation remain authoritative.
Traffic, popularity and dates are never fabricated as credibility signals.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from .cognitive_json import decode_model_json
from .evidence_graph import validate_claims


def validate_source_order(data: dict, records: list[dict]) -> list[dict]:
    """Model may reorder existing search results, not mint sources or URLs."""
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source identities")
    if not isinstance(data, dict) or set(data) != {"ranked_ids"}:
        raise ValueError("Source ranking envelope malformed")
    ranking = data["ranked_ids"]
    if (not isinstance(ranking, list) or len(ranking) != len(ids)
            or any(not isinstance(x, str) for x in ranking)
            or len(set(ranking)) != len(ranking) or set(ranking) != set(ids)):
        raise ValueError("Source ranking invented or omitted a source identity")
    by_id = {r["id"]: r for r in records}
    return [by_id[x] for x in ranking]


async def rank_sources(objective: str, records: list[dict], *, client, model: str
                       ) -> tuple[list[dict], str]:
    """Rank discovered sources based on task fit, not hardcoded domain lists.

    Model sees only provider metadata. Rankings are hypotheses until source
    bytes are independently retrieved and inspected; invalid model rankings
    cannot silently alter the URL acquisition boundary.
    """
    from google.genai import types
    from .cognitive_provider import generate_with_recovery
    if not records:
        return [], "no_sources"
    catalog = [{
        "id": r["id"], "reported_title": str(r.get("title") or "")[:180],
        "url_host": urlsplit(r["url"]).hostname,
        "published_at": r.get("published_at")
    } for r in records]
    prompt = (
        "You are a research librarian selecting sources FOR THE EXACT USER "
        "QUESTION, not for background reading. Order ONLY the supplied source "
        "IDs, strongest first. Prioritize direct answer coverage; original "
        "official/statistical/primary records, documented methods and raw "
        "figures; demonstrated subject expertise; verifiable dates and "
        "freshness relative to the requested period; corroboration and "
        "transparent corrections. Consider reputation, reach, citations, "
        "impact, visits and views ONLY where independent metadata actually "
        "establishes them; do not invent audience metrics and never equate "
        "popularity with accuracy. A headline about the institution behind "
        "a statistic is NOT a substitute for the actual requested statistic. "
        "Provider titles and domains may be misleading or redirect wrappers; "
        "treat all entries as provisional until HTTPS retrieval verifies them. "
        "Return ONLY JSON with exactly one key ranked_ids containing every "
        "supplied ID once, most directly useful first. No new IDs or URLs. "
        "\nOriginal question:\n" + objective[:3500] +
        "\nUnverified search metadata:\n" +
        json.dumps(catalog, ensure_ascii=False)[:10500])
    correction = ""
    for attempt in range(2):
        try:
            response = await generate_with_recovery(
                client, model=model, role="research", timeout=55,
                contents=prompt + correction,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1, max_output_tokens=1800))
            return validate_source_order(
                decode_model_json(getattr(response, "text", "") or ""),
                records), "model_ranked"
        except ValueError:
            correction = (
                "\nPrevious ranking violated the exact-ID contract. Return "
                "ranked_ids containing every supplied ID exactly once, "
                "without invented identifiers, comments or new fields.")
    return records, "provider_order_fallback"


def salvage_verified_claims(document: dict, spans: dict[str, dict]
                            ) -> tuple[list[dict], dict[str, int]]:
    """Salvage each valid quote independently; never relax its original check.

    A single invented citation must not throw away other valid source-byte
    quotations. Every accepted item still passes validate_claims unchanged.
    """
    if (not isinstance(document, dict) or set(document) != {"schema_version", "claims"}
            or document["schema_version"] != 1
            or not isinstance(document["claims"], list)
            or not 1 <= len(document["claims"]) <= 48):
        raise ValueError("Unsupported evidence claim envelope")
    valid, seen, rejected = [], set(), {}
    for claim in document["claims"]:
        try:
            accepted = validate_claims({"schema_version": 1, "claims": [claim]}, spans)[0]
            if accepted["id"] in seen:
                raise ValueError("Duplicate source-bound assertion")
            seen.add(accepted["id"])
            valid.append(accepted)
        except (ValueError, KeyError, TypeError) as exc:
            reason = type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)
            # Static validator error descriptions only, never raw model text.
            reason = reason[:90]
            rejected[reason] = rejected.get(reason, 0) + 1
    return valid, rejected


def validate_focus(data: dict, claims: list[dict]) -> dict:
    """Only permit model selection from independently validated claim IDs."""
    if not isinstance(data, dict) or set(data) != {
            "answers_question", "selected_ids", "missing_aspects"}:
        raise ValueError("Invalid research focus audit envelope")
    if type(data["answers_question"]) is not bool:
        raise ValueError("Invalid focus decision")
    items = data["selected_ids"]
    known = {c["id"] for c in claims}
    if (not isinstance(items, list) or len(items) > len(claims)
            or any(not isinstance(x, str) for x in items)
            or len(set(items)) != len(items) or any(x not in known for x in items)):
        raise ValueError("Focus verdict referenced unknown or duplicated claim")
    missing = data["missing_aspects"]
    if (not isinstance(missing, list) or len(missing) > 8
            or any(not isinstance(x, str) or not 5 <= len(x) <= 240
                   for x in missing)):
        raise ValueError("Invalid focus coverage gaps")
    if data["answers_question"] and not items:
        raise ValueError("No direct source-backed answer selected")
    return {"answers_question": data["answers_question"],
            "selected_ids": items, "missing_aspects": missing}


async def focus_claims(objective: str, claims: list[dict], *, client, model: str
                       ) -> tuple[list[dict], dict]:
    """Judge whether source-supported findings answer the user's actual ask.

    The model can reject irrelevant findings; it cannot authorize new facts,
    new citations, unsupported dates or modifications to source evidence.
    """
    from google.genai import types
    from .cognitive_provider import generate_with_recovery
    if not claims:
        return [], {"status": "no_valid_quotes", "missing_aspects": []}
    summary = [{
        "id": c["id"], "claim": c["claim"][:430],
        "source_url": c["source_url"], "interpretation": c["interpretation"]
    } for c in claims[:30]]
    prompt = (
        "You are a strict RESEARCH QUESTION ALIGNMENT reviewer, separate from "
        "the writing agent. Identify source-backed claims that DIRECTLY answer "
        "the user's main question. Do not substitute information about a "
        "government department, researcher, methodology or provider for "
        "requested measurements, comparisons, dates or conclusions. If the "
        "user requests numbers, favor actual figures with units, period and "
        "definitions. If they ask how something works, explanatory findings "
        "may be the direct answer. Ignore superficial thematic overlap. "
        "Never mark the objective fully answered when its essential "
        "requested information is absent. Return ONLY JSON with exactly "
        "{\"answers_question\":boolean,\"selected_ids\":[string],"
        "\"missing_aspects\":[string]}. Select IDs ONLY from the supplied "
        "independently quote-validated claims. Each missing aspect must "
        "describe a specific unaddressed part of the original task. "
        "\nOriginal user request:\n" + objective[:3500] +
        "\nSource-backed candidate claims:\n" +
        json.dumps(summary, ensure_ascii=False)[:14000])
    for attempt in range(2):
        try:
            response = await generate_with_recovery(
                client, model=model, role="research", timeout=55,
                contents=prompt + (
                    "\nPrevious JSON failed focus contract. Return only the "
                    "three required fields and existing claim IDs." if attempt else ""),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1, max_output_tokens=1500))
            decision = validate_focus(
                decode_model_json(getattr(response, "text", "") or ""), claims)
            selected = {x for x in decision["selected_ids"]}
            relevant = [x for x in claims if x["id"] in selected]
            return (relevant if decision["answers_question"] else []), {
                "status": "answers_question" if decision["answers_question"]
                          else "unanswered_objective",
                "missing_aspects": decision["missing_aspects"],
                "selected": len(relevant),
                "reviewed": len(claims)}
        except ValueError:
            continue
    return [], {"status": "focus_contract_invalid", "missing_aspects": []}
