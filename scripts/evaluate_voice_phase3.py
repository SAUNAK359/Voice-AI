#!/usr/bin/env python3
"""Frozen V11 voice qualification; never manufactures live acoustic evidence.

Input JSONL rows:
{"id":"...","device":"android-chrome","warm":true,"outcome":"ok",
 "measurement":"browser_scheduled_proxy","first_audio_ms":1200,
 "asr_ms":280,"tts_first_pcm_ms":140}
To qualify physical audio, use measurement="acoustic_loopback" and independently
record timestamps through calibrated microphone/speaker loopback hardware.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median


FIELDS=("first_audio_ms","asr_ms","tts_first_pcm_ms","interrupt_cutoff_ms")
MEASUREMENTS={"acoustic_loopback","browser_scheduled_proxy","server_first_pcm"}
OUTCOMES={"ok","failed","interrupted","timeout","busy"}


def percentile(rows,percent):
    values=sorted(rows)
    return values[math.ceil(len(values)*percent/100)-1] if values else None


def evaluate(records):
    if not isinstance(records,list):
        raise ValueError("JSONL must contain a list of records")
    seen=set()
    for row in records:
        if not isinstance(row,dict) or not set(("id","device","warm","outcome","measurement")) <= row.keys():
            raise ValueError("Invalid benchmark record contract")
        if (not isinstance(row["id"],str) or not 1<=len(row["id"])<=80
                or row["id"] in seen or not isinstance(row["device"],str)
                or not 1<=len(row["device"])<=80 or type(row["warm"]) is not bool
                or row["outcome"] not in OUTCOMES
                or row["measurement"] not in MEASUREMENTS):
            raise ValueError("Duplicate or invalid benchmark record")
        seen.add(row["id"])
        for key in FIELDS:
            value=row.get(key)
            if value is not None and (type(value) not in (float,int) or
                                     not math.isfinite(value) or value<0 or value>300000):
                raise ValueError("Invalid nonnegative latency")
        if row["outcome"]=="ok" and row.get("first_audio_ms") is None:
            raise ValueError("Success requires a real observed first-audio duration")
    ok=[row for row in records if row["outcome"]=="ok"]
    parts={}
    for row in records:
        key="|".join((row["device"],"warm" if row["warm"] else "cold",row["measurement"]))
        parts.setdefault(key,[]).append(row)
    breakdown={}
    for key,rows in sorted(parts.items()):
        successful=[r for r in rows if r["outcome"]=="ok"]
        fields={}
        for field in FIELDS:
            vals=[r[field] for r in successful if r.get(field) is not None]
            fields[field]={"count":len(vals),"p50":percentile(vals,50),
                           "p95":percentile(vals,95),"p99":percentile(vals,99)}
        breakdown[key]={"n":len(rows),"successes":len(successful),
                         "failures":len(rows)-len(successful),"metrics":fields}
    # The physical output SLO cannot be inferred from a server or browser
    # scheduled playback proxy, even if that proxy appears extremely fast.
    acoustic=[r for r in records if r["measurement"]=="acoustic_loopback" and r["warm"]]
    by_device={}
    for row in acoustic:
        by_device.setdefault(row["device"],[]).append(row)
    physical={}
    for device,group in sorted(by_device.items()):
        successful=[r["first_audio_ms"] for r in group if r["outcome"]=="ok"]
        qualified=(len(group)>=1000 and len(successful)/len(group)>=.99)
        physical[device]={
            "n":len(group),"successful":len(successful),
            "coverage_qualified":qualified,
            "first_audio_p95_ms":percentile(successful,95),
            "target_met":bool(qualified and percentile(successful,95)<=3000),
        }
    qualified=bool(physical and all(v["coverage_qualified"] for v in physical.values()))
    return {"schema_version":1,"total":len(records),"successful":len(ok),
            "failed":len(records)-len(ok),
            "completion_rate":round(len(ok)/len(records),4) if records else None,
            "breakdown":breakdown,"physical_by_device":physical,
            "physical_coverage_qualified":qualified,
            "physical_audio_slo_met":bool(qualified and
                                        all(v["target_met"] for v in physical.values())),
            "limitations":"Per-device acoustic loopback required; proxy samples cannot qualify"}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True,type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    data=args.input.read_bytes()
    if len(data)>12_000_000:raise ValueError("Benchmark exceeds bounded 12 MB")
    rows=[json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    if len(rows)>20000:raise ValueError("Benchmark exceeds 20,000 turns")
    report=evaluate(rows)
    report["input_sha256"]=hashlib.sha256(data).hexdigest()
    output=json.dumps(report,indent=2,sort_keys=True)
    if args.output:args.output.write_text(output+"\n",encoding="utf-8")
    else:print(output)


if __name__=="__main__":
    main()
