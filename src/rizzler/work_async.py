"""Async Work waiting without artificial application-level model deadlines.

Work jobs are durable and HTTP submissions return 202 immediately. When enabled,
the event loop awaits provider/model results without cancelling a task solely
because a model is slow. Provider transport failures, quota limits, explicit user
cancellation, and worker leases are separate boundaries; they are NOT disabled.
"""
from __future__ import annotations

import asyncio
import os


def async_wait_enabled() -> bool:
    """Enabled for V15 by default; opt out to restore old per-call deadlines."""
    value = os.environ.get("RIZZLER_WORK_ASYNC_WAIT", "1").strip().lower()
    if value not in ("1", "true", "yes", "on", "0", "false", "no", "off"):
        raise ValueError("RIZZLER_WORK_ASYNC_WAIT must be on or off")
    return value in ("1", "true", "yes", "on")


def stage_timeout(seconds: float) -> float | None:
    """None removes application timers; underlying provider may still fail."""
    return None if async_wait_enabled() else seconds


def wait_scope(seconds: float) -> asyncio.Timeout:
    """An async context manager; a None deadline is intentionally unbounded."""
    return asyncio.timeout(stage_timeout(seconds))
