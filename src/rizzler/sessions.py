"""In-memory demo sessions and fair bounded admission to one native inference slot.

Persistent Work is never owned by these voice turn sessions. The queue is
process-local and is not a distributed scheduling guarantee.
"""
from __future__ import annotations
import asyncio
from collections import deque
from contextlib import asynccontextmanager
import secrets
import time
from dataclasses import dataclass, field


class AdmissionBusy(RuntimeError):
    pass


class FairInference:
    """FIFO with per-owner duplicate rejection, fixed queue and bounded waits."""

    def __init__(self, max_waiting: int = 8):
        self.max_waiting = max_waiting
        self._condition = asyncio.Condition()
        self._waiting: deque[tuple[object, str]] = deque()
        self._active: tuple[object, str] | None = None

    def locked(self) -> bool:
        return self._active is not None

    @asynccontextmanager
    async def permit(self, owner: str, *, timeout: float = 2.5):
        if not owner or not 0 < timeout <= 30:
            raise ValueError("Invalid voice admission request")
        token = object()
        async with self._condition:
            if (len(self._waiting) >= self.max_waiting or
                    (self._active is not None and self._active[1] == owner) or
                    any(previous_owner == owner for _, previous_owner in self._waiting)):
                raise AdmissionBusy("Voice inference is busy")
            self._waiting.append((token, owner))
            try:
                await asyncio.wait_for(self._condition.wait_for(
                    lambda: self._active is None and
                    bool(self._waiting) and self._waiting[0][0] is token), timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                self._waiting = deque(item for item in self._waiting if item[0] is not token)
                self._condition.notify_all()
                if isinstance(exc, asyncio.TimeoutError):
                    raise AdmissionBusy("Voice inference admission timed out") from None
                raise
            self._active = (token, owner)
            self._waiting.popleft()
            self._condition.notify_all()
        try:
            yield
        finally:
            async with self._condition:
                if self._active is not None and self._active[0] is token:
                    self._active = None
                self._condition.notify_all()

    @property
    def queued(self) -> int:
        return len(self._waiting)


@dataclass
class Session:
    client_id: str
    nonce: str = field(default_factory=lambda: secrets.token_hex(16))
    history: list[dict] = field(default_factory=list)
    uploads: list[str] = field(default_factory=list)
    visuals: list[str] = field(default_factory=list)
    visual_analysis: dict | None = None
    generation: int = 0
    task: asyncio.Task | None = None
    websocket: object | None = None
    last_active: float = field(default_factory=time.monotonic)

    async def cancel(self):
        task = self.task
        if task and not task.done():
            task.cancel()
            # Native ASR/TTS kernels are not preemptible; stale generations
            # are fenced even when a native thread finishes after cancellation.
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.6)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass


class Sessions:
    def __init__(self, capacity: int = 16, idle_seconds: int = 1800):
        self.sessions: dict[str, Session] = {}
        self.capacity = capacity
        self.idle_seconds = idle_seconds
        self.inference = FairInference()

    def get(self, client_id: str) -> Session:
        now = time.monotonic()
        if client_id not in self.sessions:
            expired = [key for key, value in self.sessions.items()
                       if now - value.last_active >= self.idle_seconds and
                       value.websocket is None and
                       (value.task is None or value.task.done())]
            for key in expired:
                del self.sessions[key]
            if len(self.sessions) >= self.capacity:
                raise RuntimeError("Session capacity reached")
            self.sessions[client_id] = Session(client_id)
        session = self.sessions[client_id]
        session.last_active = now
        return session

    def reset(self, client_id: str):
        session = self.sessions.get(client_id)
        if session:
            session.history.clear()
            session.generation += 1
        return session
