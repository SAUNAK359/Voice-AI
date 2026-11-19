"""Targeted, non-destructive PowerPoint repairs with strict regression checks.

Gemini proposes a tiny patch, never a rewritten presentation. The runtime
verifies all unchanged bytes/fields, citations, numbers, section lineage and
the complete original storyboard contract before accepting it.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import re

from .cognitive_json import decode_model_json

NUMBERS = re.compile(r"(?<!\w)[+-]?\d[\d,]*(?:\.\d+)?%?(?!\w)")
EDITABLE = frozenset({"title", "message", "kind"})
SLIDE_FIELDS = frozenset({
    "title", "message", "kind", "bullets", "section_ids", "source_urls"})
TYPES = frozenset({"takeaway", "comparison", "process", "evidence", "metrics", "decision"})


def storyboard_diagnostics(document: dict) -> list[dict]:
    """Machine-actionable diagnostics; no generic 'contract_invalid' ambiguity."""
    if not isinstance(document, dict) or not isinstance(document.get("slides"), list):
        raise ValueError("Storyboard envelope not suitable for targeted repair")
    slides = document["slides"]
    issues = []
    for i, slide in enumerate(slides):
        if not isinstance(slide, dict) or set(slide) != SLIDE_FIELDS:
            # A malformed container is not safe for partial patching.
            raise ValueError(f"Slide {i+1}: invalid field set; replan from source IR")
        for key, minimum, maximum in (
                ("title", 5, 100), ("message", 15, 320)):
            value = slide[key]
            if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
                issues.append({
                    "index": i, "field": key,
                    "error": "invalid_text_length",
                    "allowed_min": minimum, "allowed_max": maximum,
                    "observed_length": len(value.strip()) if isinstance(value, str) else None})
        if slide["kind"] not in TYPES:
            issues.append({
                "index": i, "field": "kind", "error": "unsupported_slide_kind",
                "allowed": sorted(TYPES)})
    return issues


def apply_storyboard_patch(original: dict, proposed: dict, *,
                           diagnostics: list[dict]) -> dict:
    """Atomic compare-and-swap patch with unchanged-field and fact invariants."""
    if (not isinstance(proposed, dict) or set(proposed) != {"changes"}
            or not isinstance(proposed["changes"], list) or
            len(proposed["changes"]) > len(diagnostics)):
        raise ValueError("Malformed targeted storyboard patch")
    allowed = {(item["index"], item["field"]) for item in diagnostics}
    result = deepcopy(original)
    seen = set()
    for change in proposed["changes"]:
        if not isinstance(change, dict) or set(change) != {
                "index", "field", "replacement"}:
            raise ValueError("Unexpected storyboard patch fields")
        index, field, replacement = (
            change["index"], change["field"], change["replacement"])
        if (type(index) is not int or field not in EDITABLE or
                (index, field) not in allowed or (index, field) in seen or
                not isinstance(replacement, str)):
            raise ValueError("Patch attempts to change protected content")
        seen.add((index, field))
        previous = original["slides"][index][field]
        if field == "kind":
            if replacement not in TYPES:
                raise ValueError("Patch proposes unsupported layout")
        else:
            minimum, maximum = ((5,100) if field=="title" else (15,320))
            if not minimum <= len(replacement.strip()) <= maximum:
                raise ValueError("Patch does not correct field length")
            if not (Counter(NUMBERS.findall(previous)) <=
                    Counter(NUMBERS.findall(replacement))):
                raise ValueError("Patch changes or removes numerical facts")
            old_urls = set(re.findall(r"https?://[^\s\])]+", previous))
            if not old_urls.issubset(set(re.findall(
                    r"https?://[^\s\])]+", replacement))):
                raise ValueError("Patch removes citation content")
            # Avoid injecting new figures that lack evidence in old text.
            if not (Counter(NUMBERS.findall(replacement)) <=
                    Counter(NUMBERS.findall(previous))):
                raise ValueError("Patch introduces unverified numerical claims")
        result["slides"][index][field] = replacement
    if seen != allowed:
        raise ValueError("Patch leaves a diagnosed field uncorrected")
    # All slides, fields, source refs, section IDs and coverage outside the
    # diagnosed title/message/kind fields remain byte-for-byte unchanged.
    for index, (before, after) in enumerate(
            zip(original["slides"], result["slides"])):
        for field in SLIDE_FIELDS:
            if (index,field) not in allowed and before[field] != after[field]:
                raise ValueError("Patch altered an unaffected storyboard field")
    return result


async def repair_storyboard(document: dict, *, sections, sources,
                            model: str, client, failure: str) -> dict:
    """Model-directed minimal edits, independent validation, no hidden fallback.

    A permitted repair is never a creative full rewrite. If it cannot
    preserve everything proven unaffected, fail rather than silently drift.
    """
    from google.genai import types
    from .cognitive_provider import generate_with_recovery
    from .work_studio import validate_storyboard
    diagnostics = storyboard_diagnostics(document)
    if not diagnostics:
        raise ValueError("Storyboard requires nonlocal repair; no safe patch available")
    if len(diagnostics) > 12:
        raise ValueError("Storyboard exceeds bounded targeted repair budget")
    approved = {(d["index"], d["field"]) for d in diagnostics}
    slices = [{"index": i, "slide": document["slides"][i]}
              for i in sorted({index for index, field in approved})]
    prompt = (
        "You are a conservative PowerPoint repair specialist. Fix ONLY the "
        "listed invalid fields of existing slides. DO NOT rewrite the slide "
        "deck or change other fields, bullets, citations, section_ids, or "
        "existing quantitative statements. Preserve all numbers, units, "
        "comparisons and source facts; do not introduce new ones. "
        "The user goal, original research and approved sources remain "
        "authoritative. Return ONLY JSON: "
        '{"changes":[{"index":0,"field":"title|message|kind",'
        '"replacement":"corrected string"}]}. '
        "Return exactly one entry for each diagnosed field. "
        "Indices are zero-based. Never include narrative commentary. "
        "\nOriginal validator error: " + failure[:240] +
        "\nExact diagnostics: " + json.dumps(diagnostics) +
        "\nAffected slides: " + json.dumps(slices,ensure_ascii=False)[:14000] +
        "\nApproved source URLs: " + json.dumps(list(sources))[:2500])
    for attempt in range(3):
        response = await generate_with_recovery(
            client, model=model, role="work", timeout=85,
            contents=prompt + (
                "\nPrevious repair rejected; follow the listed exact constraints. "
                "Do not change protected values." if attempt else ""),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=2500, temperature=0.12))
        try:
            patch = decode_model_json(
                getattr(response,"text","") or "", max_bytes=18000)
            repaired = apply_storyboard_patch(
                document, patch, diagnostics=diagnostics)
            return validate_storyboard(repaired, sections, sources)
        except ValueError:
            if attempt == 2:
                raise
    raise ValueError("Storyboard repair budget exhausted")
