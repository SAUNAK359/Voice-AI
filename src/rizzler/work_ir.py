"""Versioned, deterministic narrative contract shared by all Work renderers.

An IR checksum proves consistency of inputs, not the truth of model claims.
Every IR is reconstructed from fenced, committed specialist checkpoints after
recovery; no second model call or untrusted plan execution is required.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


@dataclass(frozen=True)
class ArtifactIR:
    schema_version: int
    title: str
    content: str
    sections: tuple[tuple[str, str], ...]
    sources: tuple[str, ...]
    dataset_rows: int | None
    dataset_digest: str | None

    @property
    def sha256(self) -> str:
        record = {
            "schema_version": self.schema_version, "title": self.title,
            "content": self.content, "sections": self.sections,
            "sources": self.sources, "dataset_rows": self.dataset_rows,
            "dataset_digest": self.dataset_digest,
        }
        return hashlib.sha256(json.dumps(record, sort_keys=True,
            ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")).hexdigest()


def compile_ir(title: str, content: str, sources: list[str],
               dataset_summary: dict | None = None) -> ArtifactIR:
    from .work_skills import sectioned
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValueError("Artifact title must be between 1 and 120 characters")
    if not isinstance(sources, list) or len(sources) > 24 or any(
        not isinstance(s, str) or not s.startswith("https://")
        or len(s) > 2048 or any(c in s for c in "\r\n\x00")
        for s in sources
    ):
        raise ValueError("Artifact evidence must contain bounded HTTPS source URLs")
    if dataset_summary is not None and (
        not isinstance(dataset_summary, dict)
        or type(dataset_summary.get("rows")) is not int
        or dataset_summary["rows"] < 0
    ):
        raise ValueError("Invalid independently computed dataset evidence")
    sections = tuple(tuple(x) for x in sectioned(content))
    data_digest = (hashlib.sha256(json.dumps(dataset_summary, sort_keys=True,
        ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")).hexdigest() if dataset_summary is not None else None)
    return ArtifactIR(1, title, content, sections,
                      tuple(dict.fromkeys(sources)),
                      dataset_summary["rows"] if dataset_summary is not None else None,
                      data_digest)
