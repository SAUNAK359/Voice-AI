"""Model-authored editorial blueprint before expensive artifact creation.

This is a planning decision, not a static report template or a substitute for
verified source evidence. It is bounded by the existing Gemini Work gateway.
"""
from __future__ import annotations

import json

from .work_cognition import CognitiveDecisionError, structured_decision
from .work_dynamic import WorkModelConfig


SECTION = {
    "type": "object",
    "properties": {
        "heading": {"type": "string"},
        "purpose": {"type": "string"},
        "evidence_or_assumptions": {"type": "string"},
        "specific_analysis": {"type": "string"},
    },
    "required": ["heading", "purpose", "evidence_or_assumptions",
                 "specific_analysis"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "audience": {"type": "string"},
        "core_question": {"type": "string"},
        "editorial_depth": {"type": "string", "enum": [
            "brief", "professional", "comprehensive"]},
        "sections": {"type": "array", "items": SECTION},
        "presentation_strategy": {"type": "string"},
        "report_strategy": {"type": "string"},
        "evidence_gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["audience", "core_question", "editorial_depth", "sections",
                 "presentation_strategy", "report_strategy", "evidence_gaps"],
    "additionalProperties": False,
}


def validate(plan: dict) -> dict:
    if type(plan) is not dict or set(plan) != set(SCHEMA["properties"]):
        raise CognitiveDecisionError("Editorial blueprint shape invalid")
    if plan["editorial_depth"] not in ("brief", "professional", "comprehensive"):
        raise CognitiveDecisionError("Editorial blueprint depth invalid")
    for key in ("audience", "core_question", "presentation_strategy", "report_strategy"):
        if type(plan[key]) is not str or not 5 <= len(plan[key].strip()) <= 600:
            raise CognitiveDecisionError("Editorial blueprint field invalid")
    sections = plan["sections"]
    if type(sections) is not list or not 2 <= len(sections) <= 14:
        raise CognitiveDecisionError("Editorial blueprint section count invalid")
    seen = set()
    for item in sections:
        if type(item) is not dict or set(item) != set(SECTION["properties"]):
            raise CognitiveDecisionError("Editorial blueprint section invalid")
        for key, value in item.items():
            limit = 100 if key == "heading" else 450
            if type(value) is not str or not 4 <= len(value.strip()) <= limit:
                raise CognitiveDecisionError("Editorial blueprint section incomplete")
        title = item["heading"].casefold().strip()
        if title in seen:
            raise CognitiveDecisionError("Editorial blueprint repeats headings")
        seen.add(title)
    gaps = plan["evidence_gaps"]
    if (type(gaps) is not list or len(gaps) > 10 or
            any(type(g) is not str or not 4 <= len(g.strip()) <= 280 for g in gaps)):
        raise CognitiveDecisionError("Editorial blueprint evidence gaps invalid")
    return plan


async def plan_editorial(objective: str, deliverables: list[str],
                         source_urls: list[str], *, cfg=None) -> dict:
    if cfg is None:
        cfg = WorkModelConfig.from_env()
    prompt = (
        "You are the editorial architect for an expert agentic artifact studio. "
        "Interpret the user's full actual objective rather than matching keywords. "
        "Decide the necessary depth, intended reader, thesis and substantive "
        "sections required to satisfy the request. For a substantial investigation "
        "or technical report, include detailed mechanisms, examples, alternatives, "
        "risks, verifiable claims, and actionable conclusions where relevant. "
        "For a short, focused request, do not pad. The outline is not the answer: "
        "each section must specify what concrete analysis or evidence must be "
        "developed. Do not invent references, metrics or claims. Unknown facts "
        "must become explicit evidence gaps, not fictional conclusions. "
        "A written report needs a coherent detailed narrative; a presentation "
        "needs a distinct readable story with informative diagrams, tables or "
        "charts only when source evidence supports them. Never put SLIDE N: "
        "production instructions into a written report. Maintain cited original "
        "currency and units. The outline is model authored, but a separate runtime "
        "validates permissions and output integrity. "
        "\nUntrusted objective: " + json.dumps(objective[:8000]) +
        "\nRequested formats: " + json.dumps(deliverables) +
        "\nProvider-attributed source URLs only (not independently verified): " +
        json.dumps(source_urls[:24]) +
        "\nReturn only the exact structured blueprint schema."
    )
    feedback = ""
    for attempt in range(2):
        draft = await structured_decision(
            prompt + feedback, SCHEMA, cfg, max_tokens=3600)
        try:
            return validate(draft)
        except CognitiveDecisionError as exc:
            feedback = ("\nPrevious blueprint invalid: " + str(exc)[:140] +
                        ". Correct the full proposal.")
    raise CognitiveDecisionError("Editorial blueprint rejected after two attempts")


def as_instruction(plan: dict, deliverables: list[str]) -> str:
    valid = validate(plan)
    return (
        "\n\nMODEL-AUTHORED EDITORIAL BLUEPRINT (planning guidance, not independent evidence):\n" +
        json.dumps(valid, ensure_ascii=False, separators=(",", ":"))[:8000] +
        "\nUser-requested output formats: " + json.dumps(deliverables) +
        "\nDevelop the relevant sections with concrete substantive analysis. "
        "Use a unified factual source of truth but write format-appropriate material. "
        "Do not simply recite these blueprint instructions or claim research "
        "was performed when it was not. Do not omit known limitations."
    )

REPAIR_EDIT = {
    "type": "object",
    "properties": {
        "section_index": {"type": "integer"},
        "replacement_body": {"type": "string"},
    },
    "required": ["section_index", "replacement_body"],
    "additionalProperties": False,
}
REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "edits": {"type": "array", "items": REPAIR_EDIT},
        "rationale": {"type": "string"},
    },
    "required": ["title", "edits", "rationale"],
    "additionalProperties": False,
}


def apply_section_repair(ir, payload: dict, dataset_summary=None):
    """Apply model-selected edits by bounded index; untouched sections stay exact."""
    from .work_ir import compile_ir
    if type(payload) is not dict or set(payload) != set(REPAIR_SCHEMA["properties"]):
        raise CognitiveDecisionError("Invalid section repair shape")
    title, edits = payload["title"], payload["edits"]
    rationale = payload["rationale"]
    if type(title) is not str or not 5 <= len(title.strip()) <= 120:
        raise CognitiveDecisionError("Invalid repaired title")
    if type(rationale) is not str or not 8 <= len(rationale) <= 450:
        raise CognitiveDecisionError("Invalid repair rationale")
    if type(edits) is not list or not 1 <= len(edits) <= 4:
        raise CognitiveDecisionError("Model must choose one to four targeted edits")
    sections = list(ir.sections)
    indexes = set()
    for item in edits:
        if type(item) is not dict or set(item) != set(REPAIR_EDIT["properties"]):
            raise CognitiveDecisionError("Invalid section edit")
        index, body = item["section_index"], item["replacement_body"]
        if (type(index) is not int or index < 0 or index >= len(sections) or
                index in indexes):
            raise CognitiveDecisionError("Invalid or repeated section index")
        if type(body) is not str or not 40 <= len(body.strip()) <= 7500:
            raise CognitiveDecisionError("Replacement section is empty or oversized")
        indexes.add(index)
        sections[index] = (sections[index][0], body.strip())
    # Nonedited section text and immutable source list are never model-regenerated.
    content = "\n\n".join("## " + heading + "\n\n" + body
                            for heading, body in sections)
    if len(content) > 45000:
        raise CognitiveDecisionError("Repaired report exceeds renderer contract")
    revised = compile_ir(title, content, list(ir.sources), dataset_summary)
    if revised.sha256 == ir.sha256:
        raise CognitiveDecisionError("Section repair produced no changes")
    return revised


async def revise_sections(ir, objective: str, defects: list[dict],
                          dataset_summary: dict | None = None,
                          *, cfg=None):
    """Request bounded local edits from Gemini; never request a full rewrite."""
    if cfg is None:
        cfg = WorkModelConfig.from_env()
    context = [{"index": idx, "heading": heading,
                "body_excerpt": body[:1900]}
               for idx, (heading, body) in enumerate(ir.sections)]
    prompt = (
        "You are Rizzler's artifact repair editor. Diagnose the reported QA "
        "defects and select ONLY the specific existing section indices requiring "
        "revision. Preserve all other sections exactly, without summarizing "
        "or dropping them. Do not rewrite an entire report to fix one paragraph "
        "or a slide layout. Return 1-4 targeted section replacement bodies, "
        "including concrete analysis, not generic filler; each replacement "
        "must preserve verifiable facts, original currency, source limitations "
        "and nondefective conclusions. Do not invent evidence, sources, statistics "
        "or dates. Source links and uploaded source values are immutable. "
        "If a reviewer complains about layout only, improve overly dense "
        "section wording without deleting substantive findings. "
        "Only choose indexes supplied by the host; do not add unsupported tools. "
        "\nObjective: " + json.dumps(objective[:2500]) +
        "\nCurrent report title: " + json.dumps(ir.title) +
        "\nSection-indexed current content: " +
        json.dumps(context, ensure_ascii=False)[:30000] +
        "\nSpecific QA defects: " +
        json.dumps(defects, ensure_ascii=False, default=str)[:4500] +
        "\nImmutable verified dataset summary: " +
        json.dumps(dataset_summary or {}, ensure_ascii=False, default=str)[:1800] +
        "\nRespond with exactly the typed repair schema."
    )
    last_error = ""
    for attempt in range(2):
        candidate = await structured_decision(
            prompt + last_error, REPAIR_SCHEMA, cfg, max_tokens=6500)
        try:
            return apply_section_repair(ir, candidate, dataset_summary)
        except CognitiveDecisionError as exc:
            last_error = ("\nLast proposed edit was rejected: " +
                          str(exc)[:140] + ". Return a corrected repair.")
    raise CognitiveDecisionError("Model exhausted targeted section-repair attempts")
