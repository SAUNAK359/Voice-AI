"""Optional crash-safe global AI spending reservations.

Reservations are a configured conservative fixed estimate per provider call,
NOT the provider's actual invoice. A single SQLite write transaction ensures
that concurrent processes sharing the same disk cannot exceed this *reserved*
daily budget. Actual token-based charges may differ; an external cloud quota
and billing alert remain necessary. Without explicit configuration no budget
cap is imposed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import math
import os
from pathlib import Path
import sqlite3


class BudgetExceeded(RuntimeError):
    pass


class BudgetLedger:
    def __init__(self, path: str | Path, daily_limit_usd: float,
                 reservation_usd: float):
        if (not math.isfinite(daily_limit_usd) or daily_limit_usd <= 0 or
                not math.isfinite(reservation_usd) or reservation_usd <= 0 or
                reservation_usd > daily_limit_usd):
            raise ValueError("Invalid AI budget or reservation")
        path=Path(path)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("AI budget database must use an absolute, non-symlink path")
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=path
        self.limit_cents=round(daily_limit_usd*100_000_000)
        self.request_cents=round(reservation_usd*100_000_000)
        if self.request_cents < 1 or self.limit_cents < 1:
            raise ValueError("AI budget resolution too small")
        with self._conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS reservations(
                day TEXT NOT NULL, id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL, micro_usd INTEGER NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS reservations_day ON reservations(day)")

    def _conn(self):
        conn=sqlite3.connect(self.path,timeout=15)
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    @staticmethod
    def day():
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def reserve(self,service: str):
        if service not in ("voice","vision","work","research"):
            raise ValueError("Invalid AI service identifier")
        date=self.day()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            used=conn.execute(
                "SELECT COALESCE(SUM(micro_usd),0) FROM reservations WHERE day=?",
                (date,)).fetchone()[0]
            if used + self.request_cents > self.limit_cents:
                raise BudgetExceeded("Optional daily AI budget reservation exhausted")
            conn.execute("INSERT INTO reservations(day,service,micro_usd) VALUES(?,?,?)",
                         (date,service,self.request_cents))
            # Keep a small rolling retention; all rows are estimates.
            conn.execute("DELETE FROM reservations WHERE day<?",
                         ((datetime.now(timezone.utc).date()
                           - __import__("datetime").timedelta(days=35)).isoformat(),))

    def snapshot(self):
        date=self.day()
        with self._conn() as conn:
            groups=conn.execute("""SELECT service,COUNT(*),COALESCE(SUM(micro_usd),0)
                   FROM reservations WHERE day=? GROUP BY service""",(date,)).fetchall()
        used=sum(x[2] for x in groups)
        return {"day_utc":date,"budget_usd":self.limit_cents/100_000_000,
                "reserved_usd":round(used/100_000_000,8),
                "remaining_reservable_usd":round(max(0,self.limit_cents-used)/100_000_000,8),
                "requests":{name:count for name,count,_ in groups},
                "basis":"configured conservative reservation; NOT actual provider charges"}


@lru_cache(maxsize=1)
def budget_from_environment():
    limit=os.environ.get("RIZZLER_AI_DAILY_BUDGET_USD","").strip()
    request=os.environ.get("RIZZLER_AI_RESERVATION_PER_CALL_USD","").strip()
    if not limit and not request:
        return None
    if not limit or not request:
        raise ValueError("Both AI budget values are required when enabled")
    root=os.environ.get("RIZZLER_AI_BUDGET_ROOT") or os.environ.get("RIZZLER_WORK_ROOT","")
    if not root:
        raise ValueError("AI budget needs a durable root shared by all provider processes")
    return BudgetLedger(Path(root)/"ai_reservations.sqlite3",float(limit),float(request))


def reserve_provider_call(service):
    ledger=budget_from_environment()
    if ledger is not None:
        ledger.reserve(service)
