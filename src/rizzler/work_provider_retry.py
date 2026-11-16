"""Sanitized provider status classification and bounded retry admission.

Only transient 429/5xx responses are eligible for durable worker defer.
The provider's raw exception/string is NEVER logged or persisted.
"""
from __future__ import annotations

import re


def transient_code(exc: BaseException) -> str | None:
    cls = type(exc).__name__
    if cls == "DeepAgentPlanningError":
        message = str(exc)
        if message in ("provider_rate_limited", "provider_unavailable"):
            return message
        return None
    status = getattr(exc, "code", None)
    if not isinstance(status, int):
        status = getattr(exc, "status_code", None)
    if status == 429:
        return "provider_rate_limited"
    if status in (500, 502, 503, 504):
        return "provider_unavailable"
    # Local SGLang emits deliberately sanitized exception codes. Preserve
    # their status without ever parsing arbitrary provider response bodies.
    if cls == "SGLangProviderError":
        code=str(exc)
        if code == "sglang_http_status_429":
            return "provider_rate_limited"
        if code in {"sglang_http_status_500","sglang_http_status_502",
                    "sglang_http_status_503","sglang_http_status_504",
                    "sglang_transport_or_schema_error:ConnectError",
                    "sglang_transport_or_schema_error:ReadTimeout"}:
            return "provider_unavailable"
    if cls in ("ServerError", "ServiceUnavailableError"):
        return "provider_unavailable"
    if cls in ("RateLimitError", "ResourceExhausted"):
        return "provider_rate_limited"
    return None


def retry_delay(exc: BaseException) -> int:
    """Respect trusted provider RetryInfo where available; fail safe otherwise."""
    bound = getattr(exc, "retry_after_seconds", None)
    if isinstance(bound, (int, float)) and not isinstance(bound,bool):
        return max(5, min(300, int(bound)))
    details = getattr(exc, "response_json", None)
    if isinstance(details, dict):
        error = details.get("error", {})
        if isinstance(error, dict):
            for item in error.get("details", [])[:12]:
                if not isinstance(item, dict):
                    continue
                delay = item.get("retryDelay")
                if isinstance(delay, str):
                    match = re.fullmatch(r"(\d{1,3})(?:\.\d+)?s", delay)
                    if match:
                        return max(5, min(300, int(match.group(1))))
    return 60
