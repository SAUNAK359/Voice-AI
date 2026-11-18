"""Versioned agent packages; manifests are inspected, never executable code."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# A local manifest cannot mint capabilities or permissions. Each declared tool
# must already be bound to a vetted Python implementation in the host.
REGISTERED_TOOLS = {
    "research": frozenset(("grounded_research",)),
    "sql_analytics": frozenset(("analyze_sql",)),
    "orchestrator": frozenset(("deep_synthesis","hace_plan")),
    "powerpoint": frozenset(("make_presentation","inspect_artifact")),
    "word": frozenset(("render_one","inspect_artifact")),
    "excel": frozenset(("render_one","inspect_artifact")),
    "pdf_visual": frozenset(("render_one","inspect_artifact")),
    "quality": frozenset(("validate_repair","inspect_artifact")),
}
BASE = Path(__file__).with_name("agent_skills")

@dataclass(frozen=True)
class AgentPackage:
    id: str
    version: str
    skill: str
    tools: tuple[str,...]
    max_depth: int
    max_tool_calls: int
    max_model_calls: int

    def compact(self) -> dict:
        return {"id":self.id,"version":self.version,
                "tools":list(self.tools),"max_depth":self.max_depth,
                "max_tool_calls":self.max_tool_calls,
                "max_model_calls":self.max_model_calls}

def load(name: str) -> AgentPackage:
    if name not in REGISTERED_TOOLS:
        raise ValueError("Unregistered specialist package")
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("Install Deep Agents extra for YAML manifests") from exc
    root=BASE/name
    raw=(root/"manifest.yaml").read_text(encoding="utf-8")
    if len(raw)>12000:
        raise ValueError("Agent manifest exceeds budget")
    info=yaml.safe_load(raw)
    if not isinstance(info,dict) or info.get("id") != name or info.get("strategy")!="hierarchical_adaptive":
        raise ValueError("Agent manifest identity or strategy invalid")
    tools=info.get("allowed_tools")
    if (not isinstance(tools,list) or len(tools)!=len(set(tools)) or
            set(tools)!=REGISTERED_TOOLS[name]):
        raise ValueError("Manifest requested unregistered or missing tools")
    permissions=info.get("permissions",{})
    if not isinstance(permissions,dict) or (
            permissions.get("arbitrary_shell") is not False or
            permissions.get("arbitrary_network") is not False or
            permissions.get("direct_publication") is not False or
            permissions.get("owner_scoped") is not True):
        raise ValueError("Agent manifest privileges denied")
    quality=info.get("quality",{})
    if (not isinstance(quality,dict) or
            quality.get("final_gate")!="independent" or
            quality.get("require_source_lineage") is not True):
        raise ValueError("Agent package bypassed required QA")
    depth,calls,models=(info.get("max_depth"),info.get("max_tool_calls"),
                        info.get("max_model_calls"))
    if (type(depth) is not int or not 1<=depth<=7 or
            type(calls) is not int or not 1<=calls<=32 or
            type(models) is not int or not 1<=models<=12):
        raise ValueError("Agent package budget invalid")
    skill=(root/"SKILL.md").read_text(encoding="utf-8")
    if not (skill.startswith("# ") and 500<=len(skill)<=15000 and
            "## Inverted pyramid execution protocol" in skill):
        raise ValueError("Specialist skill missing depth procedure")
    version=info.get("version")
    if not isinstance(version,str) or len(version)>25:
        raise ValueError("Invalid skill version")
    return AgentPackage(name,version,skill,tuple(tools),depth,calls,models)

def catalog() -> list[dict]:
    return [load(name).compact() for name in sorted(REGISTERED_TOOLS)]
