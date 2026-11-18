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
