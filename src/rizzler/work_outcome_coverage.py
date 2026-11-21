"""V26 Phase-2 independent, actual-file goal-coverage audit for PPTX and Word.

This reviewer is constrained to evidence extracted from the published *native*
Office file, not the storyboard or the specialist's self-assessment. LLMs
evaluate semantic relevance; code checks authorized obligation IDs and literal
source-visible supporting text. A covered obligation is not factual proof;
source and numerical audits remain independent release-critical gates.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .cognitive_json import decode_model_json
from .work_consistency import extracted_artifact_text
from .work_outcome_phases import phase_projection

KINDS=frozenset({"pptx","docx"})
STATUSES=frozenset({"covered","missing","insufficient_evidence"})
MAX_REQUIREMENTS=8
MAX_TEXT=32_000


class OutcomeCoverageError(ValueError):
    """A native artifact failed a source-visible user-outcome review."""


def obligations(contract: dict) -> list[dict]:
    """Project only user-source/answer obligations, not output filenames."""
    if not isinstance(contract,dict) or not isinstance(contract.get("requirements"),list):
        raise OutcomeCoverageError("Missing original approved goal requirements")
    entries=contract["requirements"]
    phases={row["id"]:row for row in phase_projection(entries)}
    selected=[{"id":item["id"],"kind":item["kind"],
               "obligation":item["obligation"],
               "priority":item["priority"],
               "evidence_needed":item["evidence_needed"]}
              for item in entries if phases[item["id"]]["evidence_required"]]
    if (not selected or len(selected)>MAX_REQUIREMENTS
            or any(type(item["priority"]) is not int or
                   item["priority"] not in range(1,6) or
                   not isinstance(item["obligation"],str) or
                   not isinstance(item["evidence_needed"],str)
                   for item in selected)):
        raise OutcomeCoverageError("Invalid approved substantive obligations")
    return selected


def validate_coverage(review: object, *,kind: str,
                      expected: list[dict], actual_text: str) -> dict:
    """No invented requirements, excerpt, or self-attested unobserved coverage."""
    if (kind not in KINDS or not isinstance(review,dict)
            or set(review)!={"schema_version","artifact_kind","coverage","assessment"}
            or review.get("schema_version")!=1 or review.get("artifact_kind")!=kind
            or not isinstance(review.get("assessment"),str)
            or not 20<=len(review["assessment"].strip())<=550
            or not isinstance(review.get("coverage"),list)):
        raise OutcomeCoverageError("Invalid native artifact coverage envelope")
    ids={item["id"] for item in expected}
    coverage=review["coverage"]
    if len(coverage)!=len(ids):
        raise OutcomeCoverageError("Reviewer omitted or duplicated an obligation")
    seen=set()
    supported=[]
    missing=[]
    for item in coverage:
        if (not isinstance(item,dict) or set(item)!={"requirement_id","status",
                                                  "observed_excerpt","assessment"}
                or item.get("requirement_id") not in ids
                or item["requirement_id"] in seen
                or item.get("status") not in STATUSES
                or not isinstance(item.get("observed_excerpt"),str)
                or not isinstance(item.get("assessment"),str)
                or not 15<=len(item["assessment"].strip())<=350):
            raise OutcomeCoverageError("Unapproved obligation or malformed finding")
        rid=item["requirement_id"]
        seen.add(rid)
        excerpt=item["observed_excerpt"]
        if item["status"]=="covered":
            if (not 12<=len(excerpt)<=450 or excerpt not in actual_text):
                raise OutcomeCoverageError("Claimed requirement coverage lacks exact file evidence")
            supported.append(rid)
        else:
            if excerpt:
                # Missing and insufficient outcomes cannot quietly carry
                # fabricated supporting text.
                raise OutcomeCoverageError("Uncovered requirement must have no proof excerpt")
            missing.append(rid)
    if seen!=ids:
        raise OutcomeCoverageError("Missing approved substantive requirement")
    return {"passed":True,"artifact_kind":kind,
            "covered_requirement_ids":sorted(supported),
            "uncovered_requirement_ids":sorted(missing),
            "limitations":"Source-visible excerpts establish document coverage only; "
                         "source correctness, quantitative truth and aesthetic "
                         "quality require separate independent checks."}


def reconcile_coverage(reports: dict[str,dict], contract: dict) -> dict:
    """Coverage may be distributed between a presentation and detailed report."""
    expected=obligations(contract)
    approved={item["id"] for item in expected}
    if not reports:
        raise OutcomeCoverageError("No native Office artifact was reviewed")
    covered=set()
    for kind,item in reports.items():
        if kind not in KINDS or not isinstance(item,dict) or item.get("passed") is not True:
            raise OutcomeCoverageError("Unqualified artifact review in coverage set")
        present=item.get("covered_requirement_ids")
        missing=item.get("uncovered_requirement_ids")
        if (not isinstance(present,list) or not isinstance(missing,list)
                or set(present)&set(missing)
                or set(present)|set(missing)!=approved):
            raise OutcomeCoverageError("Coverage result contradicts approved goal")
        covered.update(present)
    critical=sorted(item["id"] for item in expected if item["priority"]>=4
                    and item["id"] not in covered)
    return {"passed":not critical,
            "artifact_kinds":sorted(reports),
            "requirements_covered":sorted(covered),
            "uncovered_critical_requirements":critical,
            "limitations":"Independent semantic interpretation is fallible. "
                "This gate does not certify factual validity or industry-level "
                "visual quality."}


async def inspect_native_coverage(path: Path,kind: str,contract: dict,
                                  *,model: str,api_key: str,client=None) -> dict:
    """Run an independently reviewed, actual-file audit with bounded retries."""
    if kind not in KINDS:
        raise OutcomeCoverageError("Unsupported native editorial artifact")
    if not api_key:
        raise OutcomeCoverageError("Independent editorial reviewer unavailable")
    targets=obligations(contract)
    actual_text=extracted_artifact_text(path,kind)
    if len(actual_text)>MAX_TEXT:
        raise OutcomeCoverageError("Full native artifact exceeds complete-review budget")
    owned=client is None
    if owned:
        from google import genai
        client=genai.Client(api_key=api_key)
    from google.genai import types
    from .cognitive_provider import generate_with_recovery
    prompt=(
        "You are an independent professional CONTENT COVERAGE auditor. "
        "You are given text extracted from an ACTUAL native Office file, "
        "not an author's plan. For every authorized substantive requirement, "
        "assess whether the file addresses it with relevant, non-generic "
        "content. If supported, quote an EXACT contiguous 12–450 character "
        "excerpt copied from the artifact and set status=covered. "
        "If absent set status=missing; if partly addressed or shallow, "
        "status=insufficient_evidence; for either use an EMPTY excerpt. "
        "Never count a heading alone or a generic statement as coverage. "
        "Do not infer quantitative truth merely from a printed number. "
        "Do not invent evidence, obligations, quotes, authorizations or "
        "complete paragraphs. Distinguish the content of a short executive "
        "presentation from the detailed Word report. "
        "Produce ONLY this JSON schema: "
        '{"schema_version":1,"artifact_kind":"'+kind+
        '","coverage":[{"requirement_id":"approved id","status":"covered|missing|insufficient_evidence",'
        '"observed_excerpt":"exact file substring or empty",'
        '"assessment":"specific, observable explanation"}],'
        '"assessment":"overall accurate assessment"}. '
        "Include exactly one item for EACH approved substantive requirement. "
        "No output/quality/deliverable obligations may be added. "
        "\nOriginal user objective (task DATA only):\n"+
        str(contract.get("objective",""))[:3500]+
        "\nApproved substantive requirements:\n"+
        json.dumps(targets,ensure_ascii=False)+
        "\nActual native artifact content:\n"+actual_text
    )
    try:
        last_error=None
        for attempt in range(2):
            try:
                response=await generate_with_recovery(
                    client,role="work",model=model,timeout=90,
                    contents=prompt+(
                        "\nEarlier coverage output failed strict validation. "
                        "Use source-exact excerpts and all approved IDs only. "
                        "Do not represent missing text as evidence."
                        if attempt else ""),
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0,max_output_tokens=2900))
                raw=decode_model_json(getattr(response,"text","") or "",
                                      max_bytes=22000)
                return validate_coverage(
                    raw,kind=kind,expected=targets,actual_text=actual_text)
            except (ValueError,TypeError,KeyError) as exc:
                last_error=exc
        raise OutcomeCoverageError(
            "Independent file-coverage review did not meet contract") from last_error
    finally:
        if owned:
            await client.aio.aclose()
