"""Privacy-conscious, bounded single-process HTTP operational measurements."""
from __future__ import annotations
import math
import time
from collections import Counter, deque


class Operations:
    def __init__(self, max_samples: int = 2048):
        self.started = time.time()
        self.counts = Counter()
        self.samples = deque(maxlen=max_samples)

    def record(self, method: str, route: str, status: int, ms: float):
        # Never record raw URL paths, query strings, auth tokens, or request bodies.
        route = route if route and "{" not in route else route.split("{")[0] if route else "unknown"
        key = (method if method in ("GET", "POST", "PUT", "DELETE") else "other",
               route[:64], int(status // 100) * 100)
        self.counts[key] += 1
        if math.isfinite(ms) and ms >= 0:
            self.samples.append(round(ms, 2))

    def snapshot(self) -> dict:
        values = sorted(self.samples)
        def pct(p):
            return values[math.ceil(p * len(values) / 100) - 1] if values else None
        return {
            "uptime_seconds": round(time.time() - self.started, 2),
            "requests_by_route_class": [
                {"method": m, "route": route, "status_class": status, "count": count}
                for (m, route, status), count in sorted(self.counts.items())],
            "http_latency_ms": {"samples": len(values), "p50": pct(50), "p95": pct(95),
                                "p99": pct(99)},
            "scope": "process-local HTTP metrics, excludes WebSocket and physical audio latency",
        }
