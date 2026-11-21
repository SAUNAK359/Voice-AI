"""Single opt-in V23 capability profile with per-feature overrides.

A full research/artifact profile enables experimental features coherently,
but all model/tool permissions remain governed by the WorkStore and registry.
Default mode is the complete supervised Work profile; explicit overrides can disable individual features.
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
    "RIZZLER_GOAL_CONTRACT",
    "RIZZLER_COMPONENT_PLANNING",
    "RIZZLER_AUTONOMOUS_RECOVERY",
    "RIZZLER_CANDIDATE_QUALITY",
})


EXPERIMENTAL_FEATURES = frozenset({
    "RIZZLER_CONTEXT_CONVERGENCE",
    "RIZZLER_GEMINI_NATIVE_TOOLS",
})

# Versioned V26 capabilities start OFF until migration and real acceptance.
# Unlike legacy full mode, new graph schema never activates implicitly.
V26_FEATURES = frozenset({
    "RIZZLER_V26_OUTCOME_PHASES",
    "RIZZLER_V26_CONTEXT_FABRIC",
    "RIZZLER_V26_EDITORIAL_DIRECTOR",
    "RIZZLER_V26_CROSS_ARTIFACT_QA",
})


def enabled(key: str) -> bool:
    if key not in (FEATURES | EXPERIMENTAL_FEATURES | V26_FEATURES):
        raise ValueError("Unknown V23 capability")
    profile=environ.get("RIZZLER_V23_MODE","full").lower()
    if profile not in ("off","full"):
        raise ValueError("RIZZLER_V23_MODE must be off or full")
    override=environ.get(key)
    if override is None:
        return False if key in V26_FEATURES else profile=="full"
    flag=override.strip().lower()
    if flag not in ("1","true","yes","0","false","no"):
        raise ValueError("Invalid V23 feature override")
    return flag in ("1","true","yes")
