"""Safe, actionable Work failures without prompt/credential leakage.

No exception messages, model responses, URLs, raw stack contents, or user
inputs are stored. Nested TaskGroup failures retain a typed root cause.
"""
from __future__ import annotations

import asyncio
import hashlib
import traceback
from pathlib import Path


def root_exception(exc: BaseException) -> BaseException:
    if isinstance(exc, BaseExceptionGroup):
        nested = [root_exception(x) for x in exc.exceptions]
        for item in nested:
            if not isinstance(item, asyncio.CancelledError):
                return item
        return nested[0]
    return exc


def failure_code(exc: BaseException) -> str:
    error = root_exception(exc)
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(error, "code", None)
    if isinstance(status, int):
        if status in (429, 503, 500, 502, 504, 408):
            return "provider_transient"
        if status in (401, 403):
            return "provider_authorization"
        if status == 400:
            return "provider_invalid_request"
    from .work_research_errors import ResearchQualificationError
    if isinstance(error, ResearchQualificationError):
        return "research_" + error.reason
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return "deadline_exceeded"
    if isinstance(error, (ConnectionError, OSError)):
        return "transport_unavailable"
    module = type(error).__module__
    kind = type(error).__name__
    if kind in ("BudgetExceeded", "ProviderBusy"):
        return "capacity_budget"
    if kind in ("Missing", "StaleLease", "Conflict", "PermissionError"):
        return "authorization_or_state"
    if kind in ("JSONDecodeError", "ValidationError"):
        return "schema_invalid"
    if isinstance(error, (ValueError, TypeError, AssertionError, KeyError, IndexError)):
        return "contract_invalid"
    if module.startswith(("google.genai", "google.api_core")):
        return "provider_error"
    return "internal_execution"


def failure_record(exc: BaseException, stage: str) -> dict:
    error = root_exception(exc)
    if not isinstance(stage, str) or not stage or len(stage) > 64:
        raise ValueError("Invalid diagnostic stage")
    frames = traceback.extract_tb(error.__traceback__)
    # These are source-code locations, not dynamic exception messages.
    src = [{"file": Path(f.filename).name[:90], "line": int(f.lineno)}
           for f in frames[-4:]]
    typ = type(error).__name__[:90]
    module = type(error).__module__[:100]
    from .work_research_errors import ResearchQualificationError
    research = ({"research_reason": error.reason,
                 "research_failure_categories": error.counts}
                if isinstance(error, ResearchQualificationError) else {})
    return {"stage": stage, "code": failure_code(exc),
            **research,
            "exception_type": typ, "exception_module": module,
            "locations": src,
            "fingerprint": hashlib.sha256(
                repr((stage,module,typ,src)).encode("utf-8")).hexdigest()[:20]}
