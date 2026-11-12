"""Phase 3 audit of benchmark denominators and physical vs proxy measurements."""
from __future__ import annotations

import runpy
from pathlib import Path
import importlib.util
import unittest
if importlib.util.find_spec("pytest") is None:
    raise unittest.SkipTest("Phase 3 metrics tests require app/test extras")
import pytest

evaluate=runpy.run_path(str(Path(__file__).resolve().parents[1]/
                            "scripts/evaluate_voice_phase3.py"))["evaluate"]


def row(i,measurement="browser_scheduled_proxy",outcome="ok",duration=400):
    return {"id":str(i),"device":"android-chrome","warm":True,
            "outcome":outcome,"measurement":measurement,
            "first_audio_ms":duration if outcome=="ok" else None,
            "asr_ms":250 if outcome=="ok" else None}


def test_proxy_never_qualifies_as_acoustic_measurement():
    report=evaluate([row(i) for i in range(1000)])
    assert report["total"]==1000 and report["completion_rate"]==1
    assert not report["physical_coverage_qualified"]
    assert not report["physical_audio_slo_met"]


def test_failures_remain_denominator():
    records=[row(i,"acoustic_loopback",duration=1800) for i in range(991)]
    records.extend(row(i,"acoustic_loopback",outcome="timeout")
                   for i in range(991,1000))
    report=evaluate(records)
    assert report["successful"]==991 and report["failed"]==9
    assert report["completion_rate"]==.991
    assert report["physical_coverage_qualified"]
    assert report["physical_audio_slo_met"]


def test_incomplete_or_corrupt_latency_never_passes_qualification():
    for bad in ({"id":"a","device":"chrome","warm":True,"outcome":"ok",
                 "measurement":"acoustic_loopback"},
                row(1, "acoustic_loopback", duration=-1),
                row(2, "acoustic_loopback", duration=float("nan"))):
        with pytest.raises(ValueError):
            evaluate([bad])
    with pytest.raises(ValueError,match="Duplicate"):
        evaluate([row(1),row(1)])
    assert evaluate([])["completion_rate"] is None


def test_per_device_qualification_cannot_hide_weak_device():
    desktop=[row(i,"acoustic_loopback") for i in range(1000)]
    mobile=[{**row(i+1000,"acoustic_loopback"),"device":"ios-safari"}
            for i in range(20)]
    verdict=evaluate(desktop+mobile)
    assert verdict["physical_by_device"]["android-chrome"]["coverage_qualified"]
    assert not verdict["physical_by_device"]["ios-safari"]["coverage_qualified"]
    assert not verdict["physical_audio_slo_met"]
