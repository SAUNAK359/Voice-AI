#!/usr/bin/env python3
"""Reproducible disk-streaming V26 ingestion and editable workbook qualification.

Offline real-file proof only. This does not exercise paid Gemini reliability,
multi-format editorial quality, deployment, or independent release approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import sys
from tempfile import TemporaryDirectory
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from rizzler.work_stream_analytics import (
    StreamingSQLDataset, render_profile_workbook, verify_profile_workbook)
from rizzler.work_large_uploads import sha256_file


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",required=True,help="Local authorized CSV/XLSX <=200 MB")
    parser.add_argument("--output",required=True,help="Private JSON evidence output")
    parser.add_argument("--min-bytes",type=int,default=0)
    parser.add_argument("--max-seconds",type=float,default=0)
    parser.add_argument("--max-rss-mb",type=float,default=0)
    args=parser.parse_args()
    source=Path(args.source).resolve(strict=True)
    output=Path(args.output)
    if source.is_symlink() or output.resolve()==source:
        parser.error("Unsafe source or evidence path")
    evidence={"schema_version":1,"run_utc":datetime.now(timezone.utc).isoformat(),
              "status":"NOT_QUALIFIED","release_certification":False,
              "source_content_included":False}
    start=time.perf_counter()
    try:
        with TemporaryDirectory(prefix="rizzler-v26-benchmark-") as tmp:
            dataset=StreamingSQLDataset(source)
            try:
                summary=dataset.summary
                count=dataset.query("SELECT COUNT(*) FROM dataset")["rows"][0][0]
                if count!=summary["rows"]:
                    raise ValueError("SQL count disagrees with independently streamed count")
                if summary["source_bytes"]<args.min_bytes:
                    raise ValueError("Source below requested evidence fixture size")
                workbook=Path(tmp)/"profile.xlsx"
                render_profile_workbook(workbook,summary,"Verified full-source analysis",
                        [("Full dataset profile","Source-bound aggregates only; not raw rows."),
                         ("Limitations","No source units or domain causality assumed.")],[])
                review=verify_profile_workbook(workbook,summary)
                evidence.update({
                    "status":"TECHNICAL_INGESTION_SMOKE_PASSED",
                    "source_sha256":summary["source_sha256"],
                    "source_bytes":summary["source_bytes"],
                    "source_rows":summary["rows"],
                    "columns":summary["columns"],
                    "numeric_fields_verified":review["verified_full_source_metrics"],
                    "sql_count_reconciled":True,
                    "profile_artifact_sha256":sha256_file(workbook)})
            finally:
                dataset.close()
    except Exception as exc:
        evidence["status"]="TECHNICAL_INGESTION_SMOKE_FAILED"
        evidence["error_type"]=type(exc).__name__
    evidence["elapsed_seconds"]=round(time.perf_counter()-start,3)
    # ru_maxrss is KiB on Linux, bytes on macOS; benchmark targets Linux.
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    evidence["peak_rss_mb_linux"]=round(rss/1024,2) if sys.platform.startswith("linux") else None
    if (evidence["status"]=="TECHNICAL_INGESTION_SMOKE_PASSED"
            and ((args.max_seconds and evidence["elapsed_seconds"]>args.max_seconds)
                 or (args.max_rss_mb and evidence["peak_rss_mb_linux"] is not None
                     and evidence["peak_rss_mb_linux"]>args.max_rss_mb))):
        evidence["status"]="TECHNICAL_INGESTION_SLO_FAILED"
    evidence["limitations"]=(
        "Actual source was processed without a full-file Python rows list; "
        "this evidence proves only technical ingestion/profiling/workbook reconciliation. "
        "It does not qualify Gemini, expert judgments, multi-format production "
        "artifacts or V26 release gates.")
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_name(output.name+".partial")
    temp.write_text(json.dumps(evidence,indent=2,sort_keys=True),encoding="utf-8")
    temp.replace(output)
    print(evidence["status"],"rows",evidence.get("source_rows"),"seconds",evidence["elapsed_seconds"])
    return 0 if evidence["status"]=="TECHNICAL_INGESTION_SMOKE_PASSED" else 1


if __name__=="__main__":
    raise SystemExit(main())
