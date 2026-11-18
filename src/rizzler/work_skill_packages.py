"""Hierarchical, capability-gated skill packages for the Rizzler Work Agent.

A package is NOT a prompt-only agent. The manifest constrains capabilities,
while stage instructions are progressively disclosed to each existing stage.
No package may invent a new tool or bypass the WorkStore release boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re

ROOT = Path(__file__).with_name("agent_skills")
IDENT = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
KNOWN_TOOLS = frozenset({
    "grounded_search", "source_read", "claim_review",
    "sql_profile", "sql_readonly", "numeric_verify",
    "content_outline", "section_synthesis", "editorial_review",
    "storyboard", "render_pptx", "inspect_pptx",
    "render_docx", "inspect_docx", "render_xlsx", "inspect_xlsx",
    "render_pdf", "inspect_pdf", "render_auxiliary",
    "quality_validate", "quality_repair", "quality_visual",
})
NO_SIDE_EFFECTS = frozenset(("shell", "network_unrestricted", "publish", "cross_owner"))


@dataclass(frozen=True)
class SkillPackage:
    name: str
    role: str
    capabilities: tuple[str, ...]
    max_depth: int
    max_calls: int
    stages: tuple[str, ...]
    instructions: str

    def disclose(self, depth: int, *, max_chars: int = 6000) -> str:
        """Reveal only the bounded stage detail relevant to the current branch."""
        if not 0 <= depth <= self.max_depth:
            raise ValueError("Requested skill depth outside contract")
        headline = self.instructions[:1700]
        stages = "\n".join(self.stages[:depth + 1])
        text = ("Specialist: " + self.role + "\nMission:\n" + headline +
                "\nExecutable abstraction ladder (broad-to-specific):\n" + stages +
                "\nReturn structured stage decisions and evidence, NOT private "
                "chain-of-thought. Reconcile the deepest findings with earlier "
                "assumptions; never fabricate sources or grant tool privileges.")
        return text[:max_chars]


def load_package(name: str) -> SkillPackage:
    if not isinstance(name, str) or not IDENT.fullmatch(name):
        raise ValueError("Invalid specialist ID")
    location = ROOT / name
    manifest = location / "manifest.yaml"
    skill = location / "SKILL.md"
    stages = location / "stages.json"
    if not all(p.is_file() and not p.is_symlink() for p in (manifest,skill,stages)):
        raise ValueError("Missing trusted specialist package")
    if any(p.stat().st_size > 16000 for p in (manifest,skill,stages)):
        raise ValueError("Oversized specialist package")
    # JSON is a YAML 1.2 subset; avoid a runtime YAML parser dependency and
    # accidental arbitrary YAML object construction.
    m = json.loads(manifest.read_text("utf-8"))
    t = json.loads(stages.read_text("utf-8"))
    prose = skill.read_text("utf-8")
    if set(m) != {"id", "role", "capabilities", "max_depth", "max_calls",
                  "permissions"} or m["id"] != name:
        raise ValueError("Invalid specialist manifest")
    caps = m["capabilities"]
    if (not isinstance(caps,list) or not caps or len(caps) > 12 or
            any(type(c) is not str or c not in KNOWN_TOOLS for c in caps) or
            len(set(caps)) != len(caps)):
        raise ValueError("Specialist attempted unregistered capability")
    permissions = m["permissions"]
    if not isinstance(permissions,list) or permissions or any(
            permission in NO_SIDE_EFFECTS for permission in permissions):
        raise ValueError("Specialist requested elevated permissions")
    if (type(m["max_depth"]) is not int or not 2 <= m["max_depth"] <= 6 or
            type(m["max_calls"]) is not int or not 1 <= m["max_calls"] <= 40 or
            type(m["role"]) is not str or not 8 <= len(m["role"]) <= 160 or
            not prose.startswith("#") or len(prose) < 100):
        raise ValueError("Malformed specialist skill contract")
    if (type(t) is not list or len(t) != m["max_depth"] + 1 or
            any(type(x) is not str or not 20 <= len(x) <= 700 for x in t)):
        raise ValueError("Malformed progressive skill stages")
    return SkillPackage(name,m["role"],tuple(caps),m["max_depth"],
                        m["max_calls"],tuple(t),prose)


def skill_context(name: str, *, depth: int = 3) -> str:
    package=load_package(name)
    return package.disclose(min(depth,package.max_depth))
