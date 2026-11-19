"""Cross-process Gemini admission, bounded provider recovery and truth-preserving errors.

All model calls are work only after explicit budget admission; provider slots
are leased via SQLite on the existing persistent Work volume. Expired leases
can recover after worker death. This cannot guarantee provider uptime.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
import os
from pathlib import Path
import secrets
import sqlite3
import time


class ProviderBusy(RuntimeError):
    pass


def _transient(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    if isinstance(status, int):
        return status in (408, 429, 500, 502, 503, 504)
    message = str(exc).lower()
    # This classification is for documented transport error codes only;
    # task intent and content routing must never rely on keyword matching.
    return any(token in message for token in
               (" 429", " 503", " 502", " 504", "resource_exhausted",
                "unavailable", "deadline exceeded", "service overloaded"))


class ProviderSlots:
    """Lease limited active slots across independent workers on a shared host."""

    def __init__(self, root: str | Path, *, capacity: int = 3,
                 ttl_seconds: float = 140.0):
        if type(capacity) is not int or not 1 <= capacity <= 16:
            raise ValueError("Invalid provider slot count")
        if not 15 <= ttl_seconds <= 600:
            raise ValueError("Unsafe provider lease TTL")
        path = Path(root).expanduser().resolve()
        if not path.is_absolute():
            raise ValueError("Provider storage must have absolute path")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = path / "provider_slots.sqlite3"
        self.capacity, self.ttl = capacity, ttl_seconds
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS slots(
                token TEXT PRIMARY KEY, expires REAL NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS slots_expires ON slots(expires)")
            db.execute("""CREATE TABLE IF NOT EXISTS provider_rate_events(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL, at REAL NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS provider_rate_window "
                       "ON provider_rate_events(model,at)")

    @contextmanager
    def _connect(self):
        db=sqlite3.connect(self.database,timeout=10)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def try_acquire(self, token: str) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            db.execute("DELETE FROM slots WHERE expires<=?", (now,))
            current = db.execute("SELECT count(*) FROM slots").fetchone()[0]
            if current >= self.capacity:
                return False
            db.execute("INSERT INTO slots(token,expires) VALUES(?,?)",
                       (token, now + self.ttl))
            return True

    def renew(self, token: str) -> bool:
        with self._connect() as db:
            result = db.execute("UPDATE slots SET expires=? WHERE token=? AND expires>?",
                                (time.time() + self.ttl, token, time.time()))
            return bool(result.rowcount)

    def release(self, token: str):
        with self._connect() as db:
            db.execute("DELETE FROM slots WHERE token=?", (token,))

    async def admit_model_rate(self, model: str, *, rpm: int,
                               window_seconds: float = 60.0,
                               wait_seconds: float = 75.0) -> None:
        """Shared exact sliding-window request admission across Work processes."""
        if not isinstance(model,str) or not model or len(model)>120:
            raise ValueError("Invalid rate-limit model identity")
        if type(rpm) is not int or not 1 <= rpm <= 10000:
            raise ValueError("Invalid provider requests-per-minute budget")
        if not 0.1 <= window_seconds <= 60.0 or not 0 <= wait_seconds <= 180:
            raise ValueError("Invalid provider admission window")
        deadline=time.monotonic()+wait_seconds
        while True:
            def try_reserve():
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    now=time.time()
                    db.execute("DELETE FROM provider_rate_events WHERE at<=?",
                               (now-window_seconds,))
                    rows=db.execute(
                        "SELECT at FROM provider_rate_events WHERE model=? "
                        "ORDER BY at LIMIT ?",(model,rpm)).fetchall()
                    if len(rows)<rpm:
                        db.execute("INSERT INTO provider_rate_events(model,at) "
                                   "VALUES(?,?)",(model,now))
                        return 0.0
                    return max(0.03,rows[0][0]+window_seconds-now)
            delay=await asyncio.to_thread(try_reserve)
            if delay<=0:
                return
            if time.monotonic()+delay>deadline:
                raise ProviderBusy("Configured model request rate exhausted")
            await asyncio.sleep(delay)

    @asynccontextmanager
    async def acquire(self, *, wait_seconds: float = 60.0):
        if not 0 <= wait_seconds <= 300:
            raise ValueError("Invalid provider admission deadline")
        token = secrets.token_hex(16)
        stop = time.monotonic() + wait_seconds
        while not await asyncio.to_thread(self.try_acquire, token):
            if time.monotonic() >= stop:
                raise ProviderBusy("Provider inference slots are saturated")
            await asyncio.sleep(min(0.24, max(0.01, stop - time.monotonic())))
        async def keepalive():
            while True:
                await asyncio.sleep(self.ttl / 3)
                if not await asyncio.to_thread(self.renew, token):
                    raise ProviderBusy("Provider slot lease was lost")
        guard = asyncio.create_task(keepalive())
        try:
            yield
            if guard.done() and guard.exception():
                raise ProviderBusy("Provider slot lease expired during inference")
        finally:
            guard.cancel()
            await asyncio.gather(guard, return_exceptions=True)
            await asyncio.to_thread(self.release, token)


def shared_slots() -> ProviderSlots | None:
    """Configured Work instances share an admission DB; demo-only jobs may opt out."""
    root = os.environ.get("RIZZLER_PROVIDER_SLOT_ROOT") or os.environ.get("RIZZLER_WORK_ROOT")
    if not root:
        return None
    return ProviderSlots(root, capacity=int(os.environ.get("RIZZLER_PROVIDER_SLOTS", "3")))


async def generate_with_recovery(client, *, model: str, contents, config,
                                 role: str, timeout: float = 85.0,
                                 attempts: int = 3):
    """Per-attempt cost reservation + short, bounded retries for transient errors.

    Refuses to turn failure into an invented answer. The caller validates
    provider content and schemas before treating the result as usable.
    """
    if not 1 <= attempts <= 5 or not 5 <= timeout <= 170:
        raise ValueError("Invalid model deadline/retry policy")
    slots = shared_slots()
    for attempt in range(attempts):
        try:
            from .production_guard import reserve_provider_call
            if slots is None:
                reserve_provider_call(role)
                async with asyncio.timeout(timeout):
                    return await client.aio.models.generate_content(
                        model=model, contents=contents, config=config)
            async with slots.acquire(wait_seconds=min(60, timeout)):
                # Every configured Work process respects the same actual
                # model request-rate window, not merely concurrent slots.
                from .config import Settings
                rpm=Settings.from_env().gemini_rpm
                await slots.admit_model_rate(
                    model,rpm=rpm,wait_seconds=min(90,timeout))
                reserve_provider_call(role)
                async with asyncio.timeout(timeout):
                    return await client.aio.models.generate_content(
                        model=model, contents=contents, config=config)
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except Exception as exc:
            if not _transient(exc) or attempt + 1 == attempts:
                raise
            # Bound congestion amplification; randomized retry prevents
            # synchronized retries across the three available provider slots.
            pause = min(8.0, 0.5 * (2 ** attempt)) + secrets.randbelow(250)/1000
            await asyncio.sleep(pause)
    raise RuntimeError("Provider recovery exhausted")
