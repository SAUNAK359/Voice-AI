"""Model-authored Work thinking levels, isolated by async execution task.

Gemini chooses medium/high in the Work DAG. These values control provider
thinking, not a keyword classifier. Security and resource budgets stay code-owned.
"""
from __future__ import annotations
from contextvars import ContextVar
from contextlib import contextmanager

_current: ContextVar[str] = ContextVar("work_thinking_level",default="medium")
LEVELS=frozenset(("medium","high"))

def current()->str:
    return _current.get()

@contextmanager
def use(level: str):
    if level not in LEVELS:raise ValueError("Unsupported Work thinking level")
    token=_current.set(level)
    try:yield
    finally:_current.reset(token)

def config(level: str | None=None):
    from google.genai import types
    value=level or current()
    if value not in LEVELS:raise ValueError("Unsupported Work thinking level")
    return types.ThinkingConfig(thinking_level=value)
