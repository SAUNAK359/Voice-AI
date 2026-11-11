"""Local quota admission, model circuits and privacy-safe request telemetry.

Local process limits are protective only; they are not Google's authoritative
account quotas. Multi-replica production needs a shared distributed limiter.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass


class QuotaExceeded(RuntimeError):
    pass


class CircuitOpen(RuntimeError):
    pass


class QuotaGate:
    def __init__(self, rpm: int, tpm: int):
        if rpm < 1 or tpm < 1:
            raise ValueError("Positive quota limits required")
        self.rpm, self.tpm = rpm, tpm
        self._events: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    async def reserve(self, estimated_tokens: int, max_wait: float) -> None:
        if not 1 <= estimated_tokens <= self.tpm:
            raise QuotaExceeded("Request exceeds local token allowance")
        deadline = time.monotonic() + max_wait
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._events and self._events[0][0] + 60 <= now:
                    self._events.popleft()
                if len(self._events) < self.rpm and sum(x[1] for x in self._events) + estimated_tokens <= self.tpm:
                    self._events.append((now, estimated_tokens))
                    return
                # Oldest removal always helps; loop also handles TPM bottlenecks.
                wait = max(0.01, self._events[0][0] + 60 - now) if self._events else 0.05
            if time.monotonic() + wait > deadline:
                raise QuotaExceeded("Local Gemini request quota exceeded")
            await asyncio.sleep(wait)


@dataclass
class _Circuit:
    failures: int = 0
    open_until: float = 0.0


class ModelCircuits:
    def __init__(self, threshold: int = 3, cooldown: float = 20.0):
        self.threshold, self.cooldown = threshold, cooldown
        self._models: dict[str, _Circuit] = {}

    def allow(self, model: str) -> bool:
        state = self._models.setdefault(model, _Circuit())
        if state.open_until and time.monotonic() < state.open_until:
            return False
        if state.open_until:
            state.open_until = 0.0
            state.failures = 0
        return True

    def success(self, model: str) -> None:
        self._models[model] = _Circuit()

    def failure(self, model: str, transient: bool) -> None:
        if not transient:
            return
        state = self._models.setdefault(model, _Circuit())
        state.failures += 1
        if state.failures >= self.threshold:
            state.open_until = time.monotonic() + self.cooldown


def classify_error(exc: Exception) -> str:
    """Use structured HTTP status, never raw exception text (may leak prompts)."""
    status = getattr(exc, "code", None)
    if type(status) is int:
        if status == 429: return "quota"
        if status == 404: return "model_unavailable"
        if status in (408, 500, 502, 503, 504): return "transient"
        if status in (401, 403): return "authentication"
        return "invalid_request"
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "transient"
    return "unknown"


class RequestTelemetry:
    def __init__(self, capacity: int = 500):
        self.rows: deque[dict] = deque(maxlen=capacity)

    def add(self, *, model: str, tier: str, outcome: str, error: str | None,
            elapsed_ms: float, first_text_ms: float | None,
            attempts: int, prompt_tokens: int | None, output_tokens: int | None,
            input_price: float | None, output_price: float | None) -> None:
        cost = None
        if (prompt_tokens is not None and output_tokens is not None
                and input_price is not None and output_price is not None):
            cost = round((prompt_tokens * input_price + output_tokens * output_price) / 1_000_000, 8)
        self.rows.append({
            "model": model, "tier": tier, "outcome": outcome, "error": error,
            "elapsed_ms": round(elapsed_ms, 2),
            "first_text_ms": round(first_text_ms, 2) if first_text_ms is not None else None,
            "attempts": attempts, "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens, "estimated_usd": cost,
        })

    def summary(self) -> dict:
        rows = list(self.rows)
        successes = [r for r in rows if r["outcome"] == "ok"]
        durations = sorted(r["elapsed_ms"] for r in successes)
        def p(percent: int) -> float | None:
            return durations[math.ceil(len(durations) * percent / 100) - 1] if durations else None
        costs = [r["estimated_usd"] for r in rows if r["estimated_usd"] is not None]
        return {
            "window_requests": len(rows), "successful": len(successes),
            "failed": len(rows) - len(successes), "p50_success_ms": p(50),
            "p95_success_ms": p(95), "usage_reported": sum(
                r["prompt_tokens"] is not None and r["output_tokens"] is not None for r in rows),
            "cost_known_requests": len(costs),
            "known_estimated_usd": round(sum(costs), 8) if costs else None,
            "caveat": "Process-local bounded window; costs exclude requests with unknown usage or prices",
        }
