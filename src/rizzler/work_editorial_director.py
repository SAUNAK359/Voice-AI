"""V26 editorial selection: insights and audience needs before slides.

A model chooses which original report sections are audience-worthy. Every
selected claim still points to the immutable source IR. Rejected sections
remain in the original full report and are not lost from the WorkStore.
"""
from __future__ import annotations

from dataclasses import replace
import json
from .cognitive_json import decode_model_json


def validate_editorial_plan(raw: object, *, section_count: int,
                            required_goals: list[str] | None = None) -> dict:
    if not isinstance(raw,dict) or set(raw)!={
            "schema_version","audience","thesis","selected_section_ids",
            "excluded_section_ids","goal_coverage","caveats","rationale"}:
        raise ValueError("Invalid editorial schema")
    if (raw["schema_version"]!=1 or
            not isinstance(raw["audience"],str) or
            not 3<=len(raw["audience"].strip())<=140 or
            not isinstance(raw["thesis"],str) or
            not 20<=len(raw["thesis"].strip())<=500 or
            not isinstance(raw["rationale"],str) or
            not 20<=len(raw["rationale"].strip())<=900):
        raise ValueError("Missing decision-focused editorial thesis")
    ids=raw["selected_section_ids"]
    excluded=raw["excluded_section_ids"]
    if (not isinstance(ids,list) or not ids
            or not isinstance(excluded,list)
            or any(type(i) is not int or not 0<=i<section_count
                   for i in ids+excluded)
            or len(set(ids))!=len(ids)
            or len(set(excluded))!=len(excluded)
            or set(ids)&set(excluded)
            or sorted(ids+excluded)!=list(range(section_count))):
        raise ValueError("Every original section must be explicitly included or excluded")
    if ids!=sorted(ids) or excluded!=sorted(excluded):
        raise ValueError("Editorial section order must match original evidence")
    if (not isinstance(raw["caveats"],list) or len(raw["caveats"])>12
            or any(not isinstance(item,str) or
                   not 12<=len(item.strip())<=500 for item in raw["caveats"])):
        raise ValueError("Material limitations not clearly described")
    coverage=raw["goal_coverage"]
    if (not isinstance(coverage,list) or len(coverage)>40
            or any(not isinstance(row,dict) or set(row)!={
                "goal_id","section_ids","reason"} for row in coverage)):
        raise ValueError("Malformed evidence-to-goal mapping")
    seen=set()
    for row in coverage:
        if (not isinstance(row["goal_id"],str)
                or not isinstance(row["reason"],str)
                or not 12<=len(row["reason"])<=350
                or not isinstance(row["section_ids"],list)
                or not row["section_ids"]
                or any(type(i) is not int or i not in ids
                       for i in row["section_ids"])
                or row["goal_id"] in seen):
            raise ValueError("Goal coverage invented or used omitted evidence")
        seen.add(row["goal_id"])
    if required_goals and not set(required_goals)<=seen:
        raise ValueError("Editorial plan fails required user obligations")
    return raw


async def create_editorial_plan(objective: str, ir, *,
                                goal_contract: dict | None,
                                model: str,api_key: str,
                                client=None) -> dict:
    if not api_key:
        raise RuntimeError("Editorial director requires authorized model")
    owned=client is None
    if owned:
        from google import genai
        client=genai.Client(api_key=api_key)
    from google.genai import types
    from .cognitive_provider import generate_with_recovery
    requirements=[
        {"id":r["id"],"kind":r["kind"],
         "obligation":r["obligation"],"priority":r["priority"]}
        for r in (goal_contract or {}).get("requirements",[])
        if isinstance(r,dict) and all(
            key in r for key in ("id","kind","obligation","priority"))]
    # Only evidence/analysis/decision obligations govern slide content.
    # Deliverable/quality requirements are proved by final file validators.
    critical=[r["id"] for r in requirements
              if r["kind"] not in ("deliverable","quality")
              and r["priority"]>=4]
    catalog=[{"id":i,"heading":head[:150],"content":body[:900]}
             for i,(head,body) in enumerate(ir.sections)]
    prompt=(
        "You are a senior editorial director with accountability for a "
        "professional presentation. Treat the original objective, stakeholder "
        "audience, evidence and success obligations as authoritative. "
        "Choose what genuinely belongs in a presentation; do not turn every "
        "report section into a slide. SQL execution traces, ZIP packaging, "
        "formula implementation and incidental profiling normally belong "
        "outside a client presentation unless the audience REQUESTS them. "
        "Prioritize verified analytical findings, trends, alternatives, "
        "decisions, limitations and meaningful actions. Exclude repetitive "
        "or irrelevant sections explicitly. Do not replace evidence with "
        "new facts. The source report remains intact. Preserve important "
        "uncertainties near the relevant claim, not as hidden fine print. "
        "If the source material is thin, prefer a short defensible story "
        "rather than filler. Show source-section coverage against every "
        "priority user GOAL, not a compulsory coverage of all report text. "
        "No private reasoning. Output JSON with EXACT fields: "
        '{"schema_version":1,"audience":"target reader",'
        '"thesis":"principal defensible conclusion",'
        '"selected_section_ids":[0,1],'
        '"excluded_section_ids":[2,3],'
        '"goal_coverage":[{"goal_id":"g1","section_ids":[0],'
        '"reason":"why selected evidence serves the original requirement"}],'
        '"caveats":["material evidence limitation"],'
        '"rationale":"specific editorial decision criteria"}. '
        "Section ids must be a complete disjoint partition of the "
        "original catalog. Every selected ID must be used in the required "
        "goal coverage if relevant. No new URLs or facts. "
        "\nUser request:\n"+objective[:3500]+
        "\nOutcome obligations:\n"+
        json.dumps(requirements,ensure_ascii=False)[:6500]+
        "\nOriginal source-indexed content:\n"+
        json.dumps(catalog,ensure_ascii=False)[:28000]+
        "\nOriginal approved source URLs:\n"+
        json.dumps(list(ir.sources),ensure_ascii=False)[:4000])
    last="initial"
    try:
        for iteration in range(3):
            response=await generate_with_recovery(
                client,role="work",model=model,timeout=85,
                contents=prompt+(
                    "\nPrior proposal invalid: "+last+
                    ". Repair schema/coverage only. Do not fabricate evidence."
                    if iteration else ""),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",temperature=.16,
                    max_output_tokens=4800))
            try:
                raw=decode_model_json(
                    getattr(response,"text","") or "",max_bytes=40000)
                return validate_editorial_plan(
                    raw,section_count=len(ir.sections),
                    required_goals=critical)
            except (ValueError,TypeError,KeyError) as exc:
                last=type(exc).__name__
        raise ValueError("Editorial director exhausted verified plan attempts")
    finally:
        if owned:
            await client.aio.aclose()


def project_selected_ir(ir,editorial: dict):
    """Preserves original section bytes and citations; never fabricates prose."""
    ids=editorial["selected_section_ids"]
    if not ids:
        raise ValueError("No useful content was chosen")
    return replace(ir,sections=tuple(ir.sections[i] for i in ids))


def restore_original_section_ids(slides: dict, editorial: dict) -> dict:
    """Local storyboard indices map to original source indices for lineage."""
    ids=editorial["selected_section_ids"]
    mapped=[]
    for item in slides["slides"]:
        updated=dict(item)
        updated["section_ids"]=[ids[i] for i in item["section_ids"]]
        mapped.append(updated)
    return {**slides,"slides":mapped,
            "sections_covered":sorted({
                i for item in mapped for i in item["section_ids"]})}
