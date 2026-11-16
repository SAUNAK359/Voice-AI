"""Opt-in shared memory boundary for the separate Live and Work models.

Uses the exact existing encrypted owner-scoped MemoryStore backing the Live
conversation; never copies another owner's data, raw history or new facts into
memory. This is a minimal shared-memory bridge, not the proposed Mem0 migration.
"""
from __future__ import annotations

import os
from pathlib import Path


def relevant_to_work(owner: str, objective: str) -> list[str]:
    if os.environ.get("RIZZLER_MEMORY_ENABLED", "0").strip().lower() not in (
            "1", "true", "yes"):
        return []
    from .memory import MemoryStore
    root = os.environ.get("RIZZLER_MEMORY_ROOT", "").strip()
    if not root:
        work_root = os.environ.get("RIZZLER_WORK_ROOT", "").strip()
        if not work_root:
            raise RuntimeError("Encrypted shared memory requires a persistent root")
        root = str(Path(work_root) / "private_memory")
    key = os.environ.get("RIZZLER_MEMORY_KEY", "")
    if not key:
        raise RuntimeError("Shared encrypted memory key missing")
    # Exactly the same key, directory and owner as Rizzler API.
    memory = MemoryStore(root, key)
    return memory.relevant(owner, objective[:4000], limit=3)
