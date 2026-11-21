#!/usr/bin/env python3
"""Rizzler V26 real-provider integrated qualification, no mocks.

Runs the actual V25 durable WorkStore jobs through all V26 opt-in cognitive
foundations, semantic planning and chart checks. Offline tests are separate
from paid Gemini quality. Evidence ZIP excludes private WorkStore and secrets.
Passing this limited smoke test is NOT full release certification (G00-G17).
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from zipfile import ZipFile,ZIP_DEFLATED


V26_FLAGS={
    "RIZZLER_V26_CONTEXT_FABRIC":"1",
    "RIZZLER_V26_OUTCOME_PHASES":"1",
    "RIZZLER_V26_INSIGHT_GRAPH":"1",
    "RIZZLER_V26_EDITORIAL_DIRECTOR":"1",
    "RIZZLER_V26_DOMAIN_METHODS":"1",
    "RIZZLER_V26_ARTIFACT_STRATEGY":"1",
    "RIZZLER_V26_VISUAL_CRITIC":"1",
    "RIZZLER_V26_CROSS_ARTIFACT_QA":"1",
}
TESTS=[
    "test_v26_outcome_phases.py",
    "test_v26_context_fabric.py",
    "test_v26_context_brief_runtime.py",
    "test_v26_provider_word_regression.py",
    "test_v26_editorial_strategy.py",
    "test_v26_reasoning_audit.py",
    "test_v26_visual_strategy.py",
    "test_v26_visual_critic.py",
    "test_v26_stream_analytics.py",
    "test_v26_cross_artifact_consistency.py",
    "test_v26_presentation_layout.py",
    "test_v26_final_release_gate.py",
    "test_v26_large_uploads.py",
    "test_v26_live_qualification.py",
    "test_v25_work_recovery_integration.py",
    "test_v24_storyboard_recovery.py",
]


def save(path: Path,record):
    path.write_text(json.dumps(
        record,indent=2,sort_keys=True,default=str),encoding="utf-8")


def offline(repo: Path,out: Path):
    env=os.environ.copy()
    for key in list(env):
        if key in ("GEMINI_API_KEY","GOOGLE_API_KEY") or key.startswith("RIZZLER_"):
            env.pop(key,None)
    env["PYTHONPATH"]=str(repo/"src")
    checks={}
    for test in TESTS:
        try:
            proc=subprocess.run(
                [sys.executable,"-m","unittest","discover",
                 "-s",str(repo/"tests"),"-p",test,"-v"],
                cwd=repo,env=env,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,timeout=300,check=False)
            (out/(test+".log")).write_text(proc.stdout,encoding="utf-8")
            checks[test]={"passed":proc.returncode==0,
                          "returncode":proc.returncode}
        except subprocess.TimeoutExpired:
            checks[test]={"passed":False,"reason":"test_timeout"}
        print("OFFLINE",test,checks[test]["passed"],flush=True)
    save(out/"OFFLINE_V26.json",checks)
    return checks


def package(out: Path,sha: str):
    name=("Rizzler_V26_Qualification_"+
          sha[:12]+"_"+out.name+".zip")
    target=out.parent/name
    with ZipFile(target,"w",ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if not f.is_file():
                continue
            rel=f.relative_to(out)
            if (any(p.startswith(".") or p in
                    ("private_workstore","private_slots","secrets","credentials")
                    for p in rel.parts)
                    or f.suffix.lower() in (
                        ".db",".sqlite3",".env",".key",".pem",".p12")
                    or f.stat().st_size>20_000_000):
                continue
            z.write(f,rel.as_posix())
    return target


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--expected-sha",required=True)
    ap.add_argument("--model",default="")
    options=ap.parse_args()
    repo=Path(options.repo).resolve()
    out=Path(options.output).resolve()
    out.mkdir(parents=True,exist_ok=True,mode=0o700)
    sha=subprocess.check_output(
        ["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()
    report={
        "schema_version":26,"source_sha":sha,
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "release_status":"NOT_READY",
        "v26_foundation_flags":V26_FLAGS,
        "limitations":"This is a real-provider multi-format smoke qualification; "
                      "full 18-gate release and independent human review remain required."}
    if sha!=options.expected_sha:
        report["blocking_error"]="source_commit_mismatch"
        save(out/"V26_QUALIFICATION.json",report)
        print("EVIDENCE ZIP:",package(out,sha),flush=True)
        return 1
    # The runtime flags are exact. No fallback silently disables cognition,
    # source verification, native artifact QA or user authorization checks.
    os.environ.update(V26_FLAGS)
    os.environ["RIZZLER_V23_MODE"]="full"
    os.environ["RIZZLER_CONTEXT_CONVERGENCE"]="1"
    os.environ["RIZZLER_ARTIFACT_QA"]="strict"
    os.environ["RIZZLER_GEMINI_NATIVE_TOOLS"]="1"
    os.environ["RIZZLER_ACCESS_KEY"]=secrets.token_urlsafe(32)
    os.environ["RIZZLER_WORK_SIGNING_KEY"]=secrets.token_urlsafe(48)
    os.environ["RIZZLER_WORK_ROOT"]=str(out/"private_workstore")
    os.environ["RIZZLER_PROVIDER_SLOT_ROOT"]=str(out/"private_slots")
    if options.model.strip():
        os.environ["RIZZLER_GEMINI_MODEL"]=options.model.strip()
    report["checks"]=offline(repo,out)
    report["offline_passed"]=all(x["passed"] for x in report["checks"].values())
    try:
        if os.environ.get("GEMINI_API_KEY"):
            from qualify_v25_live import run_paid
            paid=asyncio.run(run_paid(repo,out,secrets.token_hex(7)))
            report["paid"]=paid
            from qualify_v26_stream_paid import run_streamed_paid
            report["streamed_paid"]=asyncio.run(run_streamed_paid(out))
        else:
            report["blocking_error"]="missing_kaggle_GEMINI_API_KEY"
    except Exception as exc:
        report["paid_error_type"]=type(exc).__name__
    paid=report.get("paid") or {}
    report["live_passed"]=bool(
        paid.get("preflight",{}).get("passed") and
        paid.get("research",{}).get("passed") and
        paid.get("analytical",{}).get("passed"))
    report["streamed_paid_passed"]=bool(report.get("streamed_paid",{}).get("passed"))
    report["passed"]=bool(report["offline_passed"] and report["live_passed"] and report["streamed_paid_passed"])
    report["release_status"]="CANDIDATE_SMOKE_TEST_ONLY" if report["passed"] else "NOT_READY"
    report["required_release_gates"]=[f"G{i:02d}" for i in range(18)]
    report["production_signoff"]="NOT_RUN"
    report["large_file_200mb_network"]="NOT_RUN"
    report["cross_domain_benchmark_120_plus"]="NOT_RUN"
    report["blind_human_review"]="NOT_RUN"
    save(out/"V26_QUALIFICATION.json",report)
    zip_path=package(out,sha)
    print("VERDICT:",report["release_status"],flush=True)
    print("EVIDENCE ZIP:",zip_path,flush=True)
    print("SOURCE SHA:",sha,flush=True)
    return 0 if report["passed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
