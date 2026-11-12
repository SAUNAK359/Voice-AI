"""Bounded, source-preserving conversation selection for the voice model.

Extracts, never summarizes or invents prior dialogue. Recent turns stay in
chronological order; older turns are selected only on explicit term overlap.
"""
from __future__ import annotations

import re

_WORDS = re.compile(r"[a-z0-9]{3,32}")
_STOP = set("the and but for with from this that what when where why how your their "
            "will could should would have has had can are was were please about "
            "said tell now then again later previous earlier".split())


def _terms(value: str) -> set[str]:
    return set(_WORDS.findall(value.casefold())) - _STOP


def select_history(history: list[dict], query: str, *,
                   max_turns: int = 6, char_budget: int = 5400) -> list[dict]:
    """Return bounded unmodified user/assistant text, never an LLM-made summary."""
    if (not isinstance(history,list) or not isinstance(query,str) or
        not 2<=max_turns<=12 or not 900<=char_budget<=12000):
        raise ValueError("Invalid conversation context")
    rows=[]
    for item in history[-200:]:
        if (not isinstance(item,dict) or item.get("role") not in ("user","assistant") or
            not isinstance(item.get("content"),str)):
            continue
        body=item["content"][:900].strip()
        if body:
            rows.append({"role":item["role"],"content":body})
    if len(rows)<=max_turns:
        chosen=rows
    else:
        keep=set(range(max(0,len(rows)-(max_turns-2)),len(rows)))
        keywords=_terms(query)
        candidates=[]
        for idx in range(0,len(rows)-(max_turns-2)):
            matched=_terms(rows[idx]["content"]) & keywords
            if matched:
                candidates.append((len(matched),idx))
        candidates.sort(key=lambda a:(-a[0],-a[1]))
        keep.update(idx for _,idx in candidates[:max_turns-len(keep)])
        chosen=[rows[idx] for idx in sorted(keep)]
    # Keep newest turns in budget. Never silently reorder or rewrite facts.
    sizes=0
    bounded=[]
    for row in reversed(chosen):
        if sizes+len(row["content"])>char_budget:
            continue
        sizes+=len(row["content"])
        bounded.append(row)
    return list(reversed(bounded))
