"""Typed, versioned tool contracts. Model output can select, never grant capabilities."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from typing import Literal

from .work_agents import SPECS

Risk = Literal["read_only", "private_artifact", "external_action"]


@dataclass(frozen=True)
class Tool:
    name: str
    risk: Risk
    timeout_seconds: int
    description: str
    inputs: tuple[str, ...] = ()
    version: int = 1

    def public(self, enabled: bool = True) -> dict:
        return {"name": self.name, "version": self.version, "risk": self.risk,
                "timeout_seconds": self.timeout_seconds, "description": self.description,
                "required_fields": list(self.inputs),
                "state": "configured" if enabled else "unavailable"}


VOICE_TOOLS = {
    "web_search": Tool("web_search", "read_only", 22, "Source-grounded live query", ("query",)),
    "symbolic_math": Tool("symbolic_math", "read_only", 6, "Verified bounded equations", ("equations",)),
    "work_submit": Tool("work_submit", "private_artifact", 10, "Submit owner-scoped work", ("objective", "deliverables")),
    "work_status": Tool("work_status", "read_only", 5, "Read owner-scoped job status"),
    "work_cancel": Tool("work_cancel", "private_artifact", 5, "Cancel owner-scoped job"),
    "memory_save": Tool("memory_save", "private_artifact", 5, "Explicit opt-in encrypted private fact", ("text",)),
    "memory_list": Tool("memory_list", "read_only", 5, "List or retrieve private saved facts"),
    "memory_clear": Tool("memory_clear", "private_artifact", 5, "Propose deleting all owner memories"),
    "memory_clear_confirm": Tool("memory_clear_confirm", "private_artifact", 5, "Confirm explicit owner deletion"),
    "memory_remove": Tool("memory_remove", "private_artifact", 5, "Delete one owner memory", ("id",)),
}
SPECIALIST_TOOLS = {
    name: Tool(name, "read_only" if name in ("research", "sql_analytics") else "private_artifact",
               spec.sla_seconds * 2, spec.role)
    for name, spec in SPECS.items()
}
REGISTRY = {**VOICE_TOOLS, **SPECIALIST_TOOLS}


def capabilities(settings, have_work: bool, memory_enabled: bool = False) -> list[dict]:
    return [
        spec.public(
            bool(settings.gemini_api_key) if name in ("web_search", "research") else
            find_spec("sympy") is not None if name == "symbolic_math" else
            have_work if name in ("work_submit", "work_status", "work_cancel", *SPECIALIST_TOOLS) else
            memory_enabled if name.startswith("memory_") else True
        ) for name, spec in REGISTRY.items()
    ]


def require_tool(tool: str, *, explicit_private_write: bool, allowed: frozenset[str]):
    spec = REGISTRY.get(tool)
    if spec is None or tool not in allowed or spec.risk == "external_action":
        raise PermissionError("Tool is outside approved task permissions")
    if spec.risk == "private_artifact" and not explicit_private_write:
        raise PermissionError("Private artifact action requires a user request")
    return spec
