"""In-memory demo sessions, scoped cancellation and bounded turn admission."""
from __future__ import annotations
import asyncio
import secrets
from dataclasses import dataclass, field


@dataclass
class Session:
    client_id: str
    nonce: str = field(default_factory=lambda: secrets.token_hex(16))
    history: list[dict] = field(default_factory=list)
    uploads: list[str] = field(default_factory=list)
    generation: int = 0
    task: asyncio.Task | None = None
    websocket: object | None = None

    async def cancel(self):
        task = self.task
        if task and not task.done():
            task.cancel()
            # An async cancellation cannot preempt native CUDA kernels; provider
            # threading locks serialize any still-running native inference.
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.6)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass


class Sessions:
    def __init__(self, capacity: int = 16):
        self.sessions: dict[str, Session] = {}
        self.capacity = capacity
        self.inference = asyncio.Lock()

    def get(self, client_id: str) -> Session:
        if client_id not in self.sessions:
            if len(self.sessions) >= self.capacity:
                # Reject rather than silently evict another user's active state.
                raise RuntimeError('Session capacity reached')
            self.sessions[client_id] = Session(client_id)
        return self.sessions[client_id]

    def reset(self, client_id: str):
        session = self.sessions.get(client_id)
        if session:
            session.history.clear()
            session.generation += 1
        return session
