"""Research failures with safe, actionable categories and no source text leakage.

The WorkStore records an error code and static source locations; these typed
exceptions make research failures distinguishable without logging model
responses, private uploads, URLs, API messages or user prompts.
"""
from __future__ import annotations

from collections import Counter

SAFE_REASONS = frozenset({
    "invalid_frontier", "no_grounded_search_response",
    "empty_grounding_metadata", "short_search_answer",
    "missing_verified_quotes", "source_acquisition_failed",
    "research_provider_error", "invalid_provider_contract",
})


class ResearchQualificationError(ValueError):
    """Safe research-specific qualification failure, never an approval."""

    def __init__(self, reason: str, *, counts: dict[str, int] | None = None):
        if reason not in SAFE_REASONS:
            raise ValueError("Unknown research diagnostic reason")
        sanitized = {}
        for name, value in (counts or {}).items():
            if (not isinstance(name, str) or name not in SAFE_REASONS
                    or type(value) is not int or not 0 <= value <= 1000):
                raise ValueError("Unsafe research diagnostic category")
            sanitized[name] = value
        self.reason = reason
        self.counts = dict(sorted(sanitized.items()))
        super().__init__("Research could not qualify: " + reason)


def failure_categories(errors: list[BaseException]) -> dict[str, int]:
    """Aggregate only known categories; suppress all provider exception text."""
    summary: Counter[str] = Counter()
    for error in errors[:16]:
        if isinstance(error, ResearchQualificationError):
            summary[error.reason] += 1
        elif isinstance(error, (ValueError, TypeError, KeyError)):
            summary["invalid_provider_contract"] += 1
        else:
            summary["research_provider_error"] += 1
    return dict(sorted(summary.items()))
