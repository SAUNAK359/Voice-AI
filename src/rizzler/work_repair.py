"""Task-local, evidence-fenced, NONDESTRUCTIVE slide storyboard repair.

Gemini decides how to repair a diagnosed problem; the runtime permits only
small, independently checkable changes. Existing valid slides are unchanged.
No patch can invent source URLs, section IDs, or unsupported numerical facts.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import re

from .cognitive_json import decode_model_json

NUMBERS = re.compile(r"(?<!\w)[+-]?\d[\d,]*(?:\.\d+)?%?(?!\w)")
EDITABLE = frozenset({"title", "message", "kind", "bullet"})
SLIDE_FIELDS = frozenset({
    "title", "message", "kind", "bullets", "section_ids", "source_urls"})
TYPES = frozenset({"takeaway", "comparison", "process", "evidence", "metrics", "decision"})
MAX_REPAIRS = 18
MAX_SLIDES = 36


class StoryboardQualificationError(ValueError):
    """Stable, privacy-safe failure reason; never includes model text."""

    REASONS = frozenset({
        "invalid_envelope", "invalid_slide_count", "invalid_slide_fields",
        "invalid_bullets", "invalid_sections", "invalid_citations",
        "missing_section_coverage", "invalid_coverage_checksum",
        "targeted_repair_failed", "model_contract_failed",
    })

    def __init__(self, reason: str):
        if reason not in self.REASONS:
            raise ValueError("Invalid presentation qualification reason")
        self.reason = reason
        super().__init__("Presentation qualification failed: " + reason)


def _normal(value: str) -> str:
    return " ".join(value.split()).casefold()


def _numbers(value) -> Counter:
    return Counter(NUMBERS.findall(value)) if isinstance(value, str) else Counter()


def _has_placeholder(value: str) -> bool:
    return "lorem ipsum" in value.casefold()


def storyboard_diagnostics(document: dict, *, sections=None, sources=None,
                           min_slides: int = 3,
                           max_slides: int = MAX_SLIDES) -> list[dict]:
    """Identify ALL locally repairable problems, including missing section IDs.

    Structural and authorization errors are not repaired by deleting or
    rewriting existing slides. Such candidates must be replanned from the
    original immutable artifact IR.
    """
    if (not isinstance(document, dict) or
            not {"schema_version", "slides"} <= set(document) or
            set(document)-{"schema_version", "slides", "sections_covered"} or
            document.get("schema_version") != 1 or
            not isinstance(document.get("slides"), list)):
        raise StoryboardQualificationError("invalid_envelope")
    slides = document["slides"]
    if not (1 <= min_slides <= max_slides <= MAX_SLIDES and
            min_slides <= len(slides) <= max_slides):
        raise StoryboardQualificationError("invalid_slide_count")
    issues, used = [], set()
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict) or set(slide) != SLIDE_FIELDS:
            raise StoryboardQualificationError("invalid_slide_fields")
        for field, minimum, maximum in (
                ("title", 5, 100), ("message", 15, 320)):
            value = slide[field]
            if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
                issues.append({
                    "index": index, "field": field,
                    "error": "invalid_text_length",
                    "allowed_min": minimum, "allowed_max": maximum,
                    "observed_length": len(value.strip()) if isinstance(value, str) else None})
            elif _has_placeholder(value):
                raise StoryboardQualificationError("invalid_slide_fields")
        kind = slide["kind"]
        if not isinstance(kind, str) or kind not in TYPES:
            issues.append({
                "index": index, "field": "kind", "error": "unsupported_slide_kind",
                "allowed": sorted(TYPES)})
        bullets = slide["bullets"]
        if not isinstance(bullets, list) or not 2 <= len(bullets) <= 6:
            raise StoryboardQualificationError("invalid_bullets")
        for item_index, value in enumerate(bullets):
            if not isinstance(value, str) or not 15 <= len(value.strip()) <= 260:
                issues.append({
                    "index": index, "field": "bullet", "item_index": item_index,
                    "error": "invalid_bullet_length",
                    "allowed_min": 15, "allowed_max": 260,
                    "observed_length": len(value.strip()) if isinstance(value, str) else None})
            elif _has_placeholder(value):
                raise StoryboardQualificationError("invalid_bullets")
        ids=slide["section_ids"]
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 8
                or any(type(i) is not int or i < 0 or
                       (sections is not None and i >= len(sections)) for i in ids)):
            raise StoryboardQualificationError("invalid_sections")
        used.update(ids)
        citations=slide["source_urls"]
        if (not isinstance(citations, list) or len(citations) > 6
                or any(not isinstance(s, str) or
                       (sources is not None and s not in sources) for s in citations)):
            raise StoryboardQualificationError("invalid_citations")
    if sections is not None:
        missing=sorted(set(range(len(sections))) - used)
        if missing:
            if len(slides)+((len(missing)+5)//6) > MAX_SLIDES:
                raise StoryboardQualificationError("missing_section_coverage")
            issues.append({"field":"missing_sections", "section_ids":missing,
                           "error":"source_coverage_incomplete"})
    # The checksum is GENERATED METADATA, not user-provided text. It is safe
    # to recompute only when no section is missing, without model rewriting.
    if ("sections_covered" in document and
            document["sections_covered"] != sorted(used) and
            not any(x["field"]=="missing_sections" for x in issues)):
        issues.append({"field":"coverage_checksum",
                       "error":"generated_coverage_checksum_disagrees"})
    return issues


def repair_failure_reason(document: object, *, sections, sources,
                          min_slides: int = 3,
                          max_slides: int = MAX_SLIDES) -> str:
    """Return a stable diagnostic category, never untrusted source text."""
    try:
        errors=storyboard_diagnostics(
            document, sections=sections, sources=sources,
            min_slides=min_slides, max_slides=max_slides)
    except StoryboardQualificationError as exc:
        return exc.reason
    fields={issue["field"] for issue in errors}
    if "missing_sections" in fields:
        return "missing_section_coverage"
    if "coverage_checksum" in fields:
        return "invalid_coverage_checksum"
    if "bullet" in fields:
        return "invalid_bullets"
    if fields & {"title","message","kind"}:
        return "invalid_slide_fields"
    return "model_contract_failed"


def _new_slide_is_source_anchored(slide: dict, *, section_ids,
                                  sections, sources) -> None:
    """The added slide must retain literal authoritatively supplied excerpts."""
    if not isinstance(slide, dict) or set(slide) != SLIDE_FIELDS:
        raise ValueError("Added slide has unapproved fields")
    if not isinstance(slide["title"],str) or not 5<=len(slide["title"].strip())<=100:
        raise ValueError("Added slide title is invalid")
    if not isinstance(slide["message"],str) or not 15<=len(slide["message"].strip())<=320:
        raise ValueError("Added slide message is invalid")
    if not isinstance(slide["kind"],str) or slide["kind"] not in TYPES:
        raise ValueError("Added slide layout is unsupported")
    ids=slide["section_ids"]
    if (not isinstance(ids,list) or not 1<=len(ids)<=8 or
            len(set(ids))!=len(ids) or any(type(x) is not int or
                                          x not in section_ids for x in ids)):
        raise ValueError("Added slide cannot change previously covered report sections")
    refs=slide["source_urls"]
    if (not isinstance(refs,list) or len(refs)>6 or
            any(not isinstance(url,str) or url not in sources for url in refs)):
        raise ValueError("Added slide cites unapproved evidence")
    bullets=slide["bullets"]
    if (not isinstance(bullets,list) or not 2<=len(bullets)<=6 or
            any(not isinstance(x,str) or
                not 15<=len(x.strip())<=260 or _has_placeholder(x)
                for x in bullets)):
        raise ValueError("Added slide has invalid evidence excerpts")
    backing = "\n".join(sections[i][1] for i in ids)
    source_text=_normal(backing)
    if not source_text:
        raise ValueError("Cannot add a slide from an empty report section")
    if any(_normal(bullet) not in source_text for bullet in bullets):
        raise ValueError("Added slide bullets are not actual source-IR excerpts")
    for id_ in ids:
        body = _normal(sections[id_][1])
        if not any(_normal(bullet) in body for bullet in bullets):
            raise ValueError("Added slide does not cite actual content of each referenced section")
    original_numbers=set(_numbers(backing))
    for field in ("title","message"):
        if _has_placeholder(slide[field]) or not set(_numbers(slide[field])) <= original_numbers:
            raise ValueError("Added slide invented numerical facts or placeholders")


def apply_storyboard_patch(original: dict, proposed: dict, *,
                           diagnostics: list[dict],
                           sections=None, sources=None) -> dict:
    """Atomic minimal model patch; all unaffected content is byte-identical."""
    if (not isinstance(proposed, dict) or
            set(proposed)-{"changes","additional_slides"} or
            not isinstance(proposed.get("changes"), list)):
        raise ValueError("Malformed targeted storyboard patch")
    changes=proposed["changes"]
    if len(changes)>MAX_REPAIRS:
        raise ValueError("Repair proposal exceeds bounded budget")
    allowed={(item.get("index"),item["field"],item.get("item_index"))
             for item in diagnostics if item["field"] in EDITABLE}
    result=deepcopy(original)
    seen=set()
    for change in changes:
        if (not isinstance(change,dict) or
                not {"index","field","replacement"} <= set(change) or
                set(change)-{"index","field","replacement","item_index"}):
            raise ValueError("Patch changes unexpected fields")
        index, field, replacement=change["index"],change["field"],change["replacement"]
        item_index=change.get("item_index")
        key=(index,field,item_index)
        if (type(index) is not int or field not in EDITABLE or key not in allowed
                or key in seen or not isinstance(replacement,str)):
            raise ValueError("Patch changed protected or undiagnosed content")
        seen.add(key)
        before=result["slides"][index]
        previous=(before["bullets"][item_index] if field=="bullet"
                  else before[field])
        if field=="kind":
            if replacement not in TYPES:
                raise ValueError("Patch proposes unsupported slide layout")
        else:
            minimum,maximum=(5,100) if field=="title" else (
                (15,320) if field=="message" else (15,260))
            if not minimum<=len(replacement.strip())<=maximum:
                raise ValueError("Patch still violates field limits")
            if _has_placeholder(replacement):
                raise ValueError("Patch introduced filler")
            if _numbers(previous)!=_numbers(replacement):
                raise ValueError("Patch changed numerical facts or quantitative claims")
            old_urls=set(re.findall(r"https?://[^\s\])]+",previous if isinstance(previous,str) else ""))
            new_urls=set(re.findall(r"https?://[^\s\])]+",replacement))
            if not old_urls <= new_urls:
                raise ValueError("Patch removed a source reference")
        if field=="bullet":
            before["bullets"][item_index]=replacement
        else:
            before[field]=replacement
    if seen!=allowed:
        raise ValueError("Patch left a diagnosed field uncorrected")

    missing=next((x["section_ids"] for x in diagnostics
                  if x["field"]=="missing_sections"),[])
    additions=proposed.get("additional_slides",[])
    if not isinstance(additions,list) or len(additions)>len(missing):
        raise ValueError("Unexpected number of new coverage slides")
    if missing and (sections is None or sources is None):
        raise ValueError("Source-anchored section coverage requires original IR")
    covered=set()
    for slide in additions:
        _new_slide_is_source_anchored(
            slide, section_ids=set(missing), sections=sections, sources=sources)
        if set(slide["section_ids"]) & covered:
            raise ValueError("New slide duplicates repaired section coverage")
        covered.update(slide["section_ids"])
    if covered!=set(missing):
        raise ValueError("New slides do not cover all missing report sections")
    if len(result["slides"])+len(additions)>MAX_SLIDES:
        raise ValueError("Slide count exceeds established maximum")
    result["slides"].extend(deepcopy(additions))

    # All source URLs, section IDs and valid bullets of original slides
    # remain unchanged. Generated checksum is derived from actual references.
    all_ids=set()
    for slide in result["slides"]:
        all_ids.update(slide["section_ids"])
    if "sections_covered" in result or any(
            x["field"]=="coverage_checksum" for x in diagnostics):
        result["sections_covered"]=sorted(all_ids)
    for i, previous_slide in enumerate(original["slides"]):
        new_slide=result["slides"][i]
        for field in SLIDE_FIELDS:
            if field=="bullets":
                for j,old_bullet in enumerate(previous_slide["bullets"]):
                    if (i,"bullet",j) not in allowed and new_slide["bullets"][j]!=old_bullet:
                        raise ValueError("Patch modified unaffected bullet")
            elif ((i,field,None) not in allowed
                  and new_slide[field]!=previous_slide[field]):
                raise ValueError("Patch modified unaffected slide content")
    return result


async def repair_storyboard(document: dict, *, sections, sources,
                            model: str, client, failure: str,
                            min_slides: int = 3,
                            max_slides: int = MAX_SLIDES) -> dict:
    """Gemini proposes scoped edits. Validate every edit and entire final deck."""
    from google.genai import types
    from .cognitive_provider import generate_with_recovery
    from .work_studio import validate_storyboard
    issues=storyboard_diagnostics(document,sections=sections,sources=sources,
                                  min_slides=min_slides,max_slides=max_slides)
    if not issues:
        raise StoryboardQualificationError("model_contract_failed")
    editable=[i for i in issues if i["field"] in EDITABLE]
    missing=next((i["section_ids"] for i in issues
                  if i["field"]=="missing_sections"),[])
    if len(editable)>MAX_REPAIRS:
        raise StoryboardQualificationError("targeted_repair_failed")
    if not editable and not missing:
        # Only generated metadata is wrong; no content may be changed.
        updated=apply_storyboard_patch(document,{"changes":[]},
                  diagnostics=issues,sections=sections,sources=sources)
        return validate_storyboard(updated,sections,sources,
                                   min_slides=min_slides,max_slides=max_slides)
    impacted=sorted({x["index"] for x in editable})
    excerpts=[{"index":i,"original_slide":document["slides"][i]}
              for i in impacted]
    available_sections=[{"id":i,"heading":sections[i][0],
                         "source_ir_body":sections[i][1][:2000]}
                        for i in missing]
    prompt=(
        "You are the PowerPoint Context-Preserving Repair Specialist. "
        "Return only a SMALL PATCH, not a rewritten deck. The runtime "
        "will reject any loss or change of unaffected content, evidence "
        "IDs, citations or quantitative values. Fix the EXACT diagnosed "
        "title/message/kind/bullet fields. A bullet fix must provide "
        "item_index matching the zero-based original bullet index. "
        "If missing section coverage is diagnosed, append the smallest "
        "number of NEW slides that together cover ONLY those missing "
        "section IDs; every bullet on an added slide must be a VERBATIM "
        "15–260 character excerpt of the corresponding source_ir_body "
        "(ignoring whitespace/case), not invented new facts. "
        "Never alter any original section_ids, source_urls, or other "
        "original slides. New slide citations must be approved source URLs, "
        "and any figures in new title/message must occur in source_ir_body. "
        'JSON ONLY: {"changes":[{"index":0,"field":"title|message|kind|bullet",'
        '"item_index":0,"replacement":"corrected string"}],'
        '"additional_slides":[{"title":"...","message":"...",'
        '"kind":"evidence","bullets":["exact excerpt 1","exact excerpt 2"],'
        '"section_ids":[0],"source_urls":[]}]}. '
        "For title/message/kind omit item_index. Empty arrays permitted "
        "only if no matching diagnosis. No preamble, no commentary. "
        "\nValidation failure: "+str(failure)[:180]+
        "\nExact issues: "+json.dumps(issues,ensure_ascii=False)[:4200]+
        "\nOriginal affected slides: "+json.dumps(excerpts,ensure_ascii=False)[:14000]+
        "\nMissing original report sections: "+
        json.dumps(available_sections,ensure_ascii=False)[:15000]+
        "\nApproved source URLs: "+json.dumps(list(sources),ensure_ascii=False)[:3600])
    last="none"
    for attempt in range(3):
        response=await generate_with_recovery(
            client,model=model,role="work",timeout=85,
            contents=prompt+(
                "\nPrevious minimal patch was rejected for this VALIDATION "
                "reason: "+last[:200]+". Preserve source-IR excerpts and "
                "the exact protected fields." if attempt else ""),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=3800,temperature=0.12))
        try:
            proposed=decode_model_json(
                getattr(response,"text","") or "",max_bytes=22000)
            repaired=apply_storyboard_patch(document,proposed,
                         diagnostics=issues,sections=sections,sources=sources)
            return validate_storyboard(repaired,sections,sources,
                                       min_slides=min_slides,max_slides=max_slides)
        except (ValueError,TypeError,KeyError) as exc:
            last=str(exc)
    raise StoryboardQualificationError("targeted_repair_failed")
