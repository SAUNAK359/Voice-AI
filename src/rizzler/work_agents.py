"""Specialist orchestration contracts: bounded deterministic plans, never agent sprawl.

A2A and MCP are transport boundaries, not required for same-process specialists.
All execution goes through the existing fenced WorkStore and skill implementations.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ArtifactReceipt, FILE_FORMATS


@dataclass(frozen=True)
class AgentSpec:
    name: str
    role: str
    sla_seconds: int
    formats: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()

    def public(self):
        return {"name": self.name, "role": self.role, "target_seconds": self.sla_seconds,
                "formats": list(self.formats), "skill": f"agent_skills/{self.name}/SKILL.md"}


# Target durations are alert thresholds, NOT guaranteed turnaround or service SLAs.
SPECS: dict[str, AgentSpec] = {
    "research": AgentSpec("research", "Verified grounded research", 180),
    "sql_analytics": AgentSpec("sql_analytics", "Read-only SQL and deterministic data QA", 60),
    "orchestrator": AgentSpec("orchestrator", "Evidence-aware content synthesis", 150),
    "powerpoint": AgentSpec("powerpoint", "Editable presentation", 120, ("pptx",)),
    "word": AgentSpec("word", "Structured Word report", 90, ("docx",)),
    "excel": AgentSpec("excel", "Workbook and tabular deliverables", 120, ("xlsx", "csv")),
    "pdf_visual": AgentSpec("pdf_visual", "PDF, charts, web and packaged deliverables",
                            120, ("pdf", "png", "svg", "json", "md", "html", "txt", "zip")),
    "quality": AgentSpec("quality", "Independent structural and model visual delivery gates", 1800),
}
SPECIALISTS = ("research", "sql_analytics", "powerpoint", "word", "excel", "pdf_visual")
SPECIALIST_FORMATS = frozenset(fmt for name in SPECIALISTS for fmt in SPECS[name].formats)


def plan(payload: dict[str, Any]) -> list[AgentSpec]:
    formats = set(payload["deliverables"])
    uploads = payload.get("uploads", [])
    if not isinstance(uploads, list) or len(uploads) > 1:
        raise ValueError("The current SQL agent supports one uploaded dataset per job")
    tasks: list[str] = []
    if "research" in formats:
        tasks.append("research")
    if uploads:
        tasks.append("sql_analytics")
    if not uploads and "data_analysis" in formats:
        raise ValueError("Data analysis requires a source dataset")
    if not ("research" in formats):
        tasks.append("orchestrator")
    for agent in ("powerpoint", "word", "excel", "pdf_visual"):
        if formats.intersection(SPECS[agent].formats):
            tasks.append(agent)
    # A pure research or data-analysis job still needs a tracked final QA decision.
    tasks.append("quality")
    if len(tasks) != len(set(tasks)) or not tasks:
        raise ValueError("Malformed work plan")
    return [SPECS[name] for name in tasks]


def result_receipts(result: dict) -> list[ArtifactReceipt]:
    return [ArtifactReceipt(**item).validate() for item in result.get("receipts", [])]


def gate_agent(name: str, result: dict, required: set[str]) -> dict:
    """Fail closed on missing evidence, output mismatches or fictitious receipts."""
    if name not in SPECS or not isinstance(result, dict):
        raise ValueError("Unsupported agent or result")
    checks = []
    if name == "research":
        urls, text = result.get("sources"), result.get("text")
        if not isinstance(urls, list) or not urls or not all(
            isinstance(u, str) and u.startswith("https://") and len(u) <= 2048 for u in urls
        ) or not isinstance(text, str) or len(text.strip()) < 40:
            raise ValueError("Research lacks verified grounding metadata and substantive findings")
        evidence=result.get("evidence")
        if evidence is not None:
            if not isinstance(evidence,list) or len(evidence)>24 or any(
                not isinstance(item,dict) or item.get("url") not in urls
                or item.get("content_verified") is not False
                or item.get("attribution") != "provider_grounding"
                for item in evidence):
                raise ValueError("Research provenance does not match provider evidence")
        checks = ["nonempty_grounded_https_sources", "substantive_findings",
                  "provider_provenance_declared"]
    elif name == "sql_analytics":
        summary = result.get("summary")
        if not isinstance(summary, dict) or not isinstance(summary.get("rows"), int):
            raise ValueError("SQL agent is missing computed dataset statistics")
        if summary.get("sql_row_count") != summary["rows"]:
            raise ValueError("Independent SQL row count conflicts with dataset statistics")
        checks = ["readonly_sql_executed", "sql_and_profile_counts_reconcile"]
    elif name == "orchestrator":
        if not isinstance(result.get("text"), str) or len(result["text"].strip()) < 40:
            raise ValueError("Orchestrator returned insufficient content")
        checks = ["nonempty_bounded_evidence_aware_draft"]
    elif name == "quality":
        if result.get("passed") is not True or result.get("missing"):
            raise ValueError("Master quality gate refused completion")
        checks = ["all_requested_formats_have_verified_receipts", "agent_lineage_complete"]
    else:
        receipts = result_receipts(result)
        kinds = {item.kind for item in receipts}
        expected = required.intersection(SPECS[name].formats)
        if not expected or kinds != expected or len(kinds) != len(receipts):
            raise ValueError("Specialist output receipt set differs from requested formats")
        checks = ["required_formats_present", "verified_receipt_checksum_and_size"]
    return {"passed": True, "checks": checks, "policy": "deterministic_v1",
            "limits": "Structural and evidence checks; not a claim of visual or factual perfection"}


def verify_checkpoint(path: Path, receipt: ArtifactReceipt) -> bool:
    if not path.is_file() or path.is_symlink() or path.stat().st_size != receipt.byte_size:
        return False
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest() == receipt.sha256


def read_skill(name: str) -> str:
    """Load curated documentation on demand, not an untrusted execution script."""
    if name not in SPECIALISTS:
        raise ValueError("Invalid specialist name")
    file = Path(__file__).with_name("agent_skills") / name / "SKILL.md"
    content = file.read_text(encoding="utf-8")
    if not (100 <= len(content) <= 15000 and content.startswith("#")):
        raise ValueError("Specialist skill specification is missing or malformed")
    return content
