"""Reproducible latency metrics; never fabricates missing observations."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from math import ceil, isfinite
from statistics import median
from typing import Iterable

VALID_STAGES = ('asr_ms','gemini_ttft_ms','tts_first_pcm_ms','post_pause_first_audio_ms','e2e_ms')


def percentile_nearest_rank(values: Iterable[float], p: float) -> float | None:
    v = sorted(float(x) for x in values if isinstance(x, (int,float)) and not isinstance(x,bool) and isfinite(x) and x>=0)
    if not v: return None
    if not 0 < p <= 100: raise ValueError('percentile outside range')
    return v[ceil(len(v)*p/100)-1]


def summarize(records: list[dict], field: str) -> dict:
    if field not in VALID_STAGES:
        raise ValueError(f'Unknown field {field}')
    valid = [float(row[field]) for row in records if row.get('outcome') == 'ok' and isinstance(row.get(field), (int,float)) and not isinstance(row.get(field),bool) and isfinite(row[field]) and row[field] >= 0]
    if not valid:
        return {'count':0,'median_ms':None,'p95_ms':None,'min_ms':None,'max_ms':None}
    return {'count':len(valid),'median_ms':round(median(valid),1),'p95_ms':round(percentile_nearest_rank(valid,95),1),'min_ms':round(min(valid),1),'max_ms':round(max(valid),1)}


def summarize_run(records: list[dict]) -> dict:
    passed=sum(row.get('outcome')=='ok' for row in records)
    failed=sum(row.get('outcome') in ('error','failed') for row in records)
    return {'turns':len(records), 'successful':passed,'failed':failed,
            'stages':{name:summarize(records,name) for name in VALID_STAGES}}
