"""Single opt-in V23 capability profile with per-feature overrides.

A full research/artifact profile enables experimental features coherently,
but all model/tool permissions remain governed by the WorkStore and registry.
Default mode is the previously validated baseline.
"""
from __future__ import annotations

from os import environ

FEATURES=frozenset({
    "RIZZLER_COGNITIVE_PLANNER",
    "RIZZLER_COGNITIVE_EXPERTS",
    "RIZZLER_COGNITIVE_CONTENT",
    "RIZZLER_COGNITIVE_REVIEW",
    "RIZZLER_RESEARCH_FRONTIER",
    "RIZZLER_EVIDENCE_FETCH",
    "RIZZLER_CLAIM_VERIFY",
    "RIZZLER_V23_UNIFIED_RESEARCH",
    "RIZZLER_COGNITIVE_STUDIO",
    "RIZZLER_REPORT_STUDIO",
    "RIZZLER_EXCEL_STUDIO",
    "RIZZLER_SQL_EXPLORATION",
})


def enabled(key: str) -> bool:
    if key not in FEATURES:
        raise ValueError("Unknown V23 capability")
    profile=environ.get("RIZZLER_V23_MODE","off").lower()
    if profile not in ("off","full"):
        raise ValueError("RIZZLER_V23_MODE must be off or full")
    override=environ.get(key)
    if override is None:
        return profile=="full"
    flag=override.strip().lower()
    if flag not in ("1","true","yes","0","false","no"):
        raise ValueError("Invalid V23 feature override")
    return flag in ("1","true","yes")
