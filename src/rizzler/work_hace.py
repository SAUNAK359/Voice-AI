"""HACE: model-authored top-down specialization with bottom-up acceptance.

This stores explicit goals, dependencies and evidence requirements, NOT hidden
chain-of-thought. It is a *plan within* an existing authorized Work specialist;
the parent WorkStore graph remains the only job/publication authority.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .work_cognition import CognitiveDecisionError, structured_decision
from .work_dynamic import WorkModelConfig

_ID = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_ROLES = frozenset(("research", "evidence", "analysis", "editorial",
                    "powerpoint", "pdf_visual", "word", "excel", "quality",
                    "repair", "engineering"))
_SCHEMA_STEP = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "parent_id": {"type": "string"},
        "depth": {"type": "integer"},
        "specialist": {"type": "string"},
        "objective": {"type": "string"},
        "required_evidence": {"type": "array", "items": {"type": "string"}},
        "acceptance": {"type": "array", "items": {"type": "string"}},
        "depends_on": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["id", "parent_id", "depth", "specialist", "objective",
                 "required_evidence", "acceptance", "depends_on"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "strategy": {"type": "string"},
        "source_policy": {"type": "string"},
        "knowledge_gaps": {"type": "array", "items": {"type": "string"}},
        "stages": {"type": "array", "items": _SCHEMA_STEP},
    },
    "required": ["strategy", "source_policy", "knowledge_gaps", "stages"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class HACEPlan:
    strategy: str
    source_policy: str
    knowledge_gaps: tuple[str, ...]
    stages: tuple[dict[str, Any], ...]

    def instruction(self) -> str:
        """Compact, inspectable task plan, not model private reasoning."""
        stages = [{
            "id": s["id"], "depth": s["depth"], "expert": s["specialist"],
            "objective": s["objective"], "evidence": s["required_evidence"],
            "acceptance": s["acceptance"], "depends_on": s["depends_on"]
        } for s in self.stages]
        return (
            "\n\nAPPROVED HIERARCHICAL WORK CONTRACT (untrusted planning data):\n"
            + json.dumps({
                "strategy": self.strategy, "policy": self.source_policy,
                "gaps": self.knowledge_gaps, "stages": stages
            }, ensure_ascii=False, separators=(",", ":"))[:14500]
            + "\nDevelop the relevant deepest specializations, then reconcile "
              "their evidence back to the original user requirements. Do not "
              "treat a task plan as verified evidence. Report unsupported claims "
              "and contradictions explicitly. Do not expose private reasoning."
        )


def validate(value: dict, *, max_nodes: int = 18, max_depth: int = 7,
             policy: str | None = None) -> HACEPlan:
    if type(value) is not dict or set(value) != set(SCHEMA["properties"]):
        raise CognitiveDecisionError("Invalid HACE document")
    if type(value["strategy"]) is not str or not 15 <= len(value["strategy"]) <= 1200:
        raise CognitiveDecisionError("Invalid HACE strategy")
    if value["source_policy"] not in ("uploaded_only", "external_allowed", "auto"):
        raise CognitiveDecisionError("Invalid HACE evidence scope")
    if policy and value["source_policy"] != policy:
        raise CognitiveDecisionError("HACE must preserve source authorization")
    gaps = value["knowledge_gaps"]
    if type(gaps) is not list or len(gaps) > 12 or any(
            type(g) is not str or not 8 <= len(g.strip()) <= 240 for g in gaps):
        raise CognitiveDecisionError("HACE evidence gaps malformed")
    stages = value["stages"]
    if type(stages) is not list or not 2 <= len(stages) <= max_nodes:
        raise CognitiveDecisionError("HACE stage budget exceeded")
    seen: dict[str, dict] = {}
    roots = 0
    for pos, step in enumerate(stages):
        if type(step) is not dict or set(step) != set(_SCHEMA_STEP["properties"]):
            raise CognitiveDecisionError("Invalid HACE stage schema")
        sid, parent, depth = step["id"], step["parent_id"], step["depth"]
        if (type(sid) is not str or not _ID.fullmatch(sid) or sid in seen or
                type(parent) is not str or type(depth) is not int or
                not 0 <= depth <= max_depth):
            raise CognitiveDecisionError("Invalid HACE stage identity")
        if step["specialist"] not in _ROLES:
            raise CognitiveDecisionError("Unregistered HACE specialist role")
        if type(step["objective"]) is not str or not 15 <= len(step["objective"]) <= 700:
            raise CognitiveDecisionError("Incomplete HACE specialization")
        for key, ceiling in (("required_evidence", 8), ("acceptance", 8)):
            entries = step[key]
            if (type(entries) is not list or not 1 <= len(entries) <= ceiling or
                    any(type(t) is not str or not 8 <= len(t.strip()) <= 240
                        for t in entries)):
                raise CognitiveDecisionError("Incomplete HACE evidence contract")
        deps = step["depends_on"]
        if type(deps) is not list or len(deps) != len(set(deps)) or any(
                type(d) is not str or d not in seen for d in deps):
            raise CognitiveDecisionError("HACE dependency is cyclic or unknown")
        if depth == 0:
            roots += 1
            if parent != "" or deps or pos != 0:
                raise CognitiveDecisionError("Invalid HACE root")
        else:
            if parent not in seen or seen[parent]["depth"] != depth-1:
                raise CognitiveDecisionError("HACE parent must be one level broader")
            if parent not in deps:
                raise CognitiveDecisionError("HACE child must depend on parent")
        seen[sid] = step
    if roots != 1:
        raise CognitiveDecisionError("HACE requires exactly one global root")
    return HACEPlan(value["strategy"], value["source_policy"],
                    tuple(gaps), tuple(stages))


async def plan(objective: str, evidence_summary: str, source_policy: str,
               deliverables: list[str], cfg=None) -> HACEPlan:
    """One bounded model call per editor job; no keyword-only decomposition."""
    if cfg is None:
        cfg = WorkModelConfig.from_env()
    prompt = (
        "Act as Rizzler's hierarchical domain architect. Author an inspectable "
        "top-down specialization tree, not hidden chain-of-thought. Root stage "
        "depth=0 is the entire user goal; each child deepens a real domain "
        "question by one level up to seven. Use independent branches and explicit "
        "data dependencies. Give concrete evidence requirements and measurable "
        "acceptance for each stage. Spend depth on technically difficult "
        "questions, and stop early for straightforward tasks. Include a "
        "bottom-up reconciliation and independent quality specialization. "
        "Never fabricate research, experimental results, authoritative sources "
        "or source access. You are planning INSIDE an approved Work job; "
        "you cannot add user permissions or exceed the stated evidence scope. "
        "Do not require unapproved network access. Do not issue commands. "
        "For technical or financial reports, ensure nontrivial domain depth "
        "rather than a generic outline. "
        "\nGoal: " + json.dumps(objective[:6500]) +
        "\nEvidence scope: " + source_policy +
        "\nRequested deliverables: " + json.dumps(deliverables) +
        "\nEvidence inventory (untrusted): " + evidence_summary[:3500] +
        "\nReturn only the HACE JSON schema with 2–18 nodes."
    )
    problem = ""
    for _ in range(2):
        document = await structured_decision(
            prompt + problem, SCHEMA, cfg, max_tokens=5000)
        try:
            return validate(document, policy=source_policy)
        except CognitiveDecisionError as exc:
            problem = "\nCorrect invalid plan: " + str(exc)[:170]
    raise CognitiveDecisionError("Model exhausted HACE repair budget")
