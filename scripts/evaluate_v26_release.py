#!/usr/bin/env python3
"""Evaluate the V26 18-gate release manifest without fabricating evidence.

Example:
 python scripts/evaluate_v26_release.py --evidence /path/to/release-evidence \
     --scope research --scope office-documents --output /tmp/release-decision.json

Missing gates are NOT_RUN. Production qualification requires independent
operator attestation signed with the separately provisioned verification key.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/"src"))
from rizzler.work_release_gate import evaluate_release


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--evidence",type=Path,required=True)
    parser.add_argument("--scope",action="append",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--source-sha",default="")
    args=parser.parse_args()
    commit=args.source_sha or subprocess.check_output(
        ["git","-C",str(PROJECT),"rev-parse","HEAD"],
        text=True).strip()
    key=os.environ.get("RIZZLER_RELEASE_VERIFICATION_KEY","")
    # Never print, export or persist the verification key.
    verdict=evaluate_release(
        args.evidence,source_sha=commit,supported_scope=args.scope,
        operator_verification_key=key.encode("utf-8") if len(key)>=32 else None)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(
        json.dumps(verdict,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("V26 RELEASE:",verdict["status"])
    print("Source:",commit)
    print("Failed gates:",len(verdict["failed"]))
    print("Not-run gates:",len(verdict["not_run"]))
    print("Decision file:",args.output)
    return 0 if verdict["status"]=="PRODUCTION_QUALIFIED_FOR_DECLARED_SCOPE" else 2


if __name__=="__main__":
    raise SystemExit(main())
