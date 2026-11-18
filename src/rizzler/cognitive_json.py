"""Strict, bounded decoding for model-authored cognitive contracts."""
from __future__ import annotations
import json
import re


def decode_model_json(raw: str, *, max_bytes: int = 30000) -> dict:
    if not isinstance(raw, str) or not 2 <= len(raw.encode("utf-8")) <= max_bytes:
        raise ValueError("Model JSON outside permitted response budget")
    text = raw.strip().lstrip("\ufeff")
    fence = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text,
                         flags=re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Model returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Model contract must be an object")
    return data
