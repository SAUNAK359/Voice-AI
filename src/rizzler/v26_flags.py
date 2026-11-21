"""V26 staged capability controls: opt in to qualified schema transitions.

Unlike the legacy full-profile switches, V26 migrations default OFF. Enabling
an incomplete dependency group fails closed rather than silently substituting
new prompts into an unqualified execution chain.
"""
from __future__ import annotations

from os import environ

FEATURES=frozenset({
    "RIZZLER_V26_CONTEXT_FABRIC",
    "RIZZLER_V26_OUTCOME_PHASES",
    "RIZZLER_V26_INSIGHT_GRAPH",
    "RIZZLER_V26_EDITORIAL_DIRECTOR",
    "RIZZLER_V26_DOMAIN_METHODS",
    "RIZZLER_V26_ARTIFACT_STRATEGY",
    "RIZZLER_V26_VISUAL_CRITIC",
    "RIZZLER_V26_CROSS_ARTIFACT_QA",
    "RIZZLER_V26_ADAPTIVE_RECOVERY",
    "RIZZLER_V26_PROVIDER_GATEWAY",
    "RIZZLER_V26_TELEMETRY",
    "RIZZLER_V26_LARGE_UPLOADS",
    "RIZZLER_V26_STREAM_ANALYTICS",
})


def enabled(name: str) -> bool:
    if name not in FEATURES:
        raise ValueError("Unrecognized V26 feature")
    value=environ.get(name, "0").strip().casefold()
    if value not in ("0","1","true","false","yes","no"):
        raise ValueError("Invalid V26 feature setting")
    return value in ("1","true","yes")


def foundation_enabled() -> bool:
    """Prerequisites are explicit; partial mixed-version states are unsafe."""
    selected={name for name in (
        "RIZZLER_V26_CONTEXT_FABRIC",
        "RIZZLER_V26_OUTCOME_PHASES",
        "RIZZLER_V26_INSIGHT_GRAPH") if enabled(name)}
    if selected and len(selected)!=3:
        raise ValueError("V26 evidence/phase/graph foundations must be switched together")
    return bool(selected)
