"""Shared, fail-closed Gemini Work admission, model failover and telemetry.

Every gateway invocation is limited *before* it reaches Google. SQLite WAL
provides process-shared RPM/estimated-TPM reservations, one or more leased
in-flight slots, model-specific cooldowns and bounded waits on a single host.
This is not a replacement for Google's actual quota enforcement or WorkStore.
Only configured operator models are eligible; HTTP 429 never fans out to
alternate models because project-level quotas may be shared.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{1,120}$")


class WorkProviderUnavailable(RuntimeError):
    def __init__(self, status_code: int, retry_after_seconds: int = 60):
        self.status_code = status_code
        self.retry_after_seconds = max(5, min(300, int(retry_after_seconds)))
        super().__init__("provider_rate_limited" if status_code == 429
                         else "provider_unavailable")


def model_sequence(primary: str) -> tuple[str, ...]:
    alt = os.environ.get("RIZZLER_WORK_FALLBACK_MODELS",
                         os.environ.get("RIZZLER_WORK_FALLBACK_MODEL",
                                        "gemini-3.7-flash,gemini-3.8-flash"))
    candidates = [primary] + [x.strip() for x in alt.split(",") if x.strip()]
    models = tuple(dict.fromkeys(candidates))
    if (not 1 <= len(models) <= 3 or
            any(not _MODEL.fullmatch(name) for name in models)):
        raise ValueError("Invalid bounded Gemini Work model configuration")
    return models


def provider_status(exc: BaseException) -> int | None:
    """Inspect nested provider exceptions without logging private messages."""
    seen: set[int] = set()
    def visit(err: BaseException, level: int = 0) -> int | None:
        if id(err) in seen or level > 8:
            return None
        seen.add(id(err))
        for field in ("status_code", "code"):
            status = getattr(err, field, None)
            if isinstance(status, int) and not isinstance(status, bool) and 400 <= status <= 599:
                return status
        response = getattr(err, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int) and 400 <= status <= 599:
            return status
        for child in getattr(err, "exceptions", ()):
            code = visit(child, level + 1)
            if code is not None:
                return code
        for child in (getattr(err, "__cause__", None), getattr(err, "__context__", None)):
            if isinstance(child, BaseException):
                code = visit(child, level + 1)
                if code is not None:
                    return code
        return None
    return visit(exc)


def _config_float(key: str, default: float, minimum: float, maximum: float) -> float:
    value = float(os.environ.get(key, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError("Invalid Gemini Work admission setting: " + key)
    return value


class GeminiWorkGate:
    """Cross-process provider admission on a shared, writable Work root."""

    def __init__(self, root: str | Path | None = None):
        path = Path(root or os.environ.get("RIZZLER_WORK_ROOT") or
                    (Path(tempfile.gettempdir()) / "rizzler-work-admission"))
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = path / "gemini_work_admission.sqlite3"
        with sqlite3.connect(self.db, timeout=10) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        self.rpm = int(_config_float("RIZZLER_WORK_PROVIDER_RPM", 6, 1, 1000))
        self.tpm = int(_config_float("RIZZLER_WORK_PROVIDER_TPM", 24000, 1000, 10_000_000))
        self.parallel = int(_config_float("RIZZLER_WORK_PROVIDER_PARALLEL", 1, 1, 8))
        self.gap = _config_float("RIZZLER_WORK_PROVIDER_GAP_SECONDS", 1.5, 0, 30)
        self.wait = _config_float("RIZZLER_WORK_PROVIDER_WAIT_SECONDS", 35, 1, 180)
        self.lease = _config_float("RIZZLER_WORK_PROVIDER_LEASE_SECONDS", 180, 30, 900)
        with self._tx() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS requests(
                called REAL NOT NULL, model TEXT NOT NULL, budget INTEGER NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS active(
                id TEXT PRIMARY KEY, model TEXT NOT NULL, expires REAL NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS circuits(
                model TEXT PRIMARY KEY, failures INTEGER NOT NULL,
                open_until REAL NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS requests_called ON requests(called)")

    @contextmanager
    def _tx(self):
        conn = sqlite3.connect(self.db, timeout=10, isolation_level=None)
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def acquire(self, model: str, budget: int) -> str:
        if not _MODEL.fullmatch(model) or budget < 1:
            raise ValueError("Invalid Work provider reservation")
        # Do not deadlock large prompts: a single call may reserve up to TPM
        # but cannot ask for a budget bigger than the configured cap.
        budget = min(self.tpm, budget)
        deadline = time.monotonic() + self.wait
        while True:
            now = time.time()
            with self._tx() as c:
                c.execute("DELETE FROM requests WHERE called<?", (now - 60,))
                c.execute("DELETE FROM active WHERE expires<?", (now,))
                project = c.execute(
                    "SELECT open_until FROM circuits WHERE model='__project__'"
                ).fetchone()
                if project and project[0] > now:
                    raise WorkProviderUnavailable(429, int(project[0] - now) + 1)
                row = c.execute(
                    "SELECT open_until FROM circuits WHERE model=?", (model,)
                ).fetchone()
                if row and row[0] > now:
                    raise WorkProviderUnavailable(503, int(row[0] - now) + 1)
                calls, used, latest = c.execute(
                    "SELECT COUNT(*),COALESCE(SUM(budget),0),MAX(called) FROM requests"
                ).fetchone()
                active = c.execute("SELECT COUNT(*) FROM active").fetchone()[0]
                permitted = (calls < self.rpm and used + budget <= self.tpm and
                             active < self.parallel and
                             (latest is None or now - latest >= self.gap))
                if permitted:
                    uid = secrets.token_hex(12)
                    c.execute("INSERT INTO active(id,model,expires) VALUES(?,?,?)",
                              (uid, model, now + self.lease))
                    c.execute("INSERT INTO requests VALUES(?,?,?)",
                              (now, model, budget))
                    return uid
            if time.monotonic() >= deadline:
                raise WorkProviderUnavailable(429, 60)
            await asyncio.sleep(min(1.0, deadline - time.monotonic()))

    def release(self, uid: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM active WHERE id=?", (uid,))

    def record(self, model: str, status: int | None) -> None:
        with self._tx() as c:
            if status == 429:
                # 429 often applies to the entire Google project. Prevent
                # unrelated queued Work jobs from immediately retrying it.
                c.execute("""INSERT INTO circuits(model,failures,open_until)
                    VALUES('__project__',1,?)
                    ON CONFLICT(model) DO UPDATE SET
                    failures=excluded.failures,open_until=excluded.open_until""",
                    (time.time()+60,))
            elif status in (500, 502, 503, 504):
                old = c.execute(
                    "SELECT failures FROM circuits WHERE model=?", (model,)
                ).fetchone()
                failures = min(6, (old[0] if old else 0) + 1)
                cooldown = min(300, 20 * (2 ** (failures - 1)))
                c.execute("""INSERT INTO circuits(model,failures,open_until)
                    VALUES(?,?,?) ON CONFLICT(model) DO UPDATE SET
                    failures=excluded.failures,open_until=excluded.open_until""",
                    (model, failures, time.time() + cooldown))
            elif status is None:
                c.execute("DELETE FROM circuits WHERE model=?", (model,))

    def metrics(self) -> dict:
        with self._tx() as c:
            now = time.time()
            calls = c.execute(
                "SELECT COUNT(*) FROM requests WHERE called>?", (now - 60,)
            ).fetchone()[0]
            active = c.execute(
                "SELECT COUNT(*) FROM active WHERE expires>?", (now,)
            ).fetchone()[0]
            circuits = c.execute(
                "SELECT COUNT(*) FROM circuits WHERE open_until>?", (now,)
            ).fetchone()[0]
        return {"calls_last_60_seconds": calls, "active": active,
                "model_circuits_open": circuits, "rpm_limit": self.rpm,
                "estimated_tpm_limit": self.tpm, "parallel_limit": self.parallel}

    async def run(self, models: tuple[str, ...],
                  call: Callable[[str], Awaitable[T]], *,
                  prompt_characters: int, max_output_tokens: int) -> T:
        if not models or max_output_tokens < 1 or prompt_characters < 0:
            raise ValueError("Invalid Gemini Work call")
        # Approximate input token budget. Deliberately conservative and
        # enforced on requests; token reporting from Google is authoritative.
        reservation = max(256, (prompt_characters + 2) // 3) + max_output_tokens
        latest: WorkProviderUnavailable | None = None
        for model in models:
            try:
                uid = await self.acquire(model, reservation)
            except WorkProviderUnavailable as exc:
                if exc.status_code == 429:
                    raise
                latest = exc
                continue
            try:
                from .production_guard import reserve_provider_call
                reserve_provider_call("work")
                result = await call(model)
                self.record(model, None)
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                status = provider_status(exc)
                self.record(model, status)
                if status == 429:
                    raise WorkProviderUnavailable(429) from None
                if status in (500, 502, 503, 504):
                    latest = WorkProviderUnavailable(status)
                    continue
                # Invalid authentication/schema or unknown Python errors must
                # not be concealed by a fallback model.
                raise
            finally:
                self.release(uid)
        raise latest or WorkProviderUnavailable(503)


async def gemini_content(cfg, prompt: str, *, schema: dict | None = None,
                         max_output_tokens: int = 6000,
                         system_instruction: str | None = None):
    """Single structured/native Gemini request with per-call provider failover."""
    from google import genai
    from google.genai import types
    gate = GeminiWorkGate()
    async def invoke(model: str):
        client = genai.Client(api_key=cfg.gemini_api_key)
        try:
            args = {"max_output_tokens": max_output_tokens}
            if schema is not None:
                args.update(response_mime_type="application/json",
                            response_json_schema=schema)
            if system_instruction:
                args["system_instruction"] = system_instruction
            return await client.aio.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(**args))
        finally:
            await client.aio.aclose()
    return await gate.run(model_sequence(cfg.gemini_model), invoke,
                          prompt_characters=len(prompt) + len(system_instruction or ""),
                          max_output_tokens=max_output_tokens)

try:
    from langchain_core.rate_limiters import BaseRateLimiter
except ImportError:
    # Work deployments without optional Deep Agents can still use this
    # gateway for native Gemini research, structured decisions and QA.
    class BaseRateLimiter:
        pass


class DeepAgentsWorkLimiter(BaseRateLimiter):
    """LangChain rate_limiter protocol backed by the same cross-process gate.

    LangChain invokes aacquire immediately before each individual model request,
    even inside Deep Agents subagents. A bounded reservation is made then
    released, retaining the global RPM, estimated TPM and model cooldown.
    The model call itself is bounded by the Work provider timeout. Compact
    one-call planning remains the preferred path.
    """
    def __init__(self, model: str):
        self.model=model

    async def aacquire(self, *, blocking: bool = True) -> bool:
        if not blocking:
            return False
        gate=GeminiWorkGate()
        uid=await gate.acquire(self.model, 3000)
        gate.release(uid)
        from .production_guard import reserve_provider_call
        reserve_provider_call("work")
        return True

    def acquire(self, *, blocking: bool = True) -> bool:
        if not blocking:
            return False
        return asyncio.run(self.aacquire(blocking=True))
