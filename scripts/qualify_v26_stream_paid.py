#!/usr/bin/env python3
"""Paid, real-V26 streaming Work smoke trial; no mock models or predeclared pass.

Run only from qualify_v26_live.py. This validates a real >10K-row
end-to-end Work job with independent source arithmetic and actual file QA.
Passing this one fixture is not 200MB qualification or a release signoff.
"""
from __future__ import annotations

import asyncio
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import secrets
import shutil

from rizzler.artifacts import verify_artifact
from rizzler.work_large_uploads import sha256_file
from rizzler.work_store import WorkStore
from rizzler.work_worker import WorkWorker
from rizzler.work_quality import inspect_artifact
from rizzler.work_stream_analytics import analyze_streaming_sql

FIXTURE_ROWS = 15_017
KINDS = frozenset({"pptx", "docx", "pdf", "xlsx", "zip"})


def fixture(root: Path) -> tuple[Path, dict]:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "synthetic_v26_stream.csv"
    expected_imports = 0
    expected_exports = 0
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("quarter", "imports", "exports", "region"))
        for i in range(FIXTURE_ROWS):
            imp, exp = 100 + i % 13, 90 + i % 11
            writer.writerow((f"Q{i % 4 + 1}", imp, exp,
                             ("north", "south", "east")[i % 3]))
            expected_imports += imp
            expected_exports += exp
    return path, {"imports": expected_imports,
                  "exports": expected_exports, "rows": FIXTURE_ROWS,
                  "sha256": sha256_file(path)}


async def run_streamed_paid(out: Path) -> dict:
    import os
    previous = os.environ.get("RIZZLER_V26_STREAM_ANALYTICS")
    os.environ["RIZZLER_V26_STREAM_ANALYTICS"] = "1"
    report = {
        "passed": False, "source": "synthetic_authorized_fixture",
        "live_gemini_required": True,
        "format_scope": sorted(KINDS),
        "streaming": True,
        "limitations": "Not a live 200MB trial, 120-task benchmark or release certificate",
    }
    phase="fixture_creation"
    try:
        path, expected = fixture(out / "private_workstore" / "live_fixture")
        phase="local_upload_registration"
        store = WorkStore(out / "private_workstore")
        source = path.read_bytes()
        # This bounded fixture exercises the >10K-row Work path, not 200MB HTTP
        # upload transport. The dedicated 200MB bench separately tests disk I/O.
        uploaded = store.register_upload(
            "v26_stream_owner", path.name, source)
        phase="work_job_submission"
        objective = (
            "Produce an executive, source-grounded comparative report for the "
            "uploaded SYNTHETIC 15,017-row import/export dataset. Use the actual "
            "full-source totals, explicitly state the source is fictional, "
            "analyze concentration and numerical limitations without inventing "
            "statistical significance. Deliver a native editable Excel profile "
            "(not all original rows), PowerPoint, Word, PDF and ZIP. "
            "Every numerical statement must be traceable to the source.")
        job = store.submit(
            "v26_stream_owner", objective, sorted(KINDS),
            "v26_stream_" + secrets.token_hex(8), [uploaded["id"]],
            requested_formats=sorted(KINDS))
        phase="work_agent_execution"
        processed = await WorkWorker(store).once()
        phase="source_oracle_and_artifact_review"
        status = store.get("v26_stream_owner", job["id"])["status"]
        qa = store.quality_report("v26_stream_owner", job["id"])
        # Failed downstream tasks previously exposed only "job_status: failed".
        # Export strictly typed diagnostics; never user content, full prompts
        # or the private WorkStore. This makes failed CI triage actionable.
        stages=store.agent_steps("v26_stream_owner",job["id"])
        diagnostics=store.diagnostics("v26_stream_owner",job["id"])
        report.update({"worker_processed": bool(processed),
                       "job_status": status,
                       "master_quality_passed": bool(
                           (qa.get("quality") or {}).get("passed")),
                       "stage_diagnostics":[{
                           "specialist":s.get("agent"),
                           "status":s.get("status"),
                           "error_code":s.get("error_code")}
                           for s in stages],
                       "failure_categories":[{
                           "stage":d.get("stage"),
                           "code":d.get("code"),
                           "exception_module":d.get("exception_module"),
                           "exception_type":d.get("exception_type"),
                           "http_status":d.get("http_status")}
                           for d in diagnostics[:30]]})
        oracle = await asyncio.to_thread(
            analyze_streaming_sql, store.upload("v26_stream_owner", uploaded["id"]))
        summary = oracle["summary"]
        numeric = summary.get("numeric_exact", {})
        report["source_sha256"] = summary.get("source_sha256")
        report["source_rows"] = summary.get("rows")
        report["source_arithmetic_reconciled"] = (
            summary.get("rows") == expected["rows"]
            and summary.get("source_sha256") == expected["sha256"]
            and int(Decimal(numeric.get("imports", {}).get("sum", "-1"))) == expected["imports"]
            and int(Decimal(numeric.get("exports", {}).get("sum", "-1"))) == expected["exports"])
        observed = set()
        reports = {}
        if status == "completed":
            from rizzler.contracts import ArtifactReceipt
            published=store.artifacts("v26_stream_owner", job["id"])
            bundle_receipts={}
            for item in published:
                if item["kind"]!="zip":
                    source_path,metadata=store.artifact(
                        "v26_stream_owner",item["id"])
                    bundle_receipts[source_path.name]=verify_artifact(
                        source_path,item["kind"])
            for artifact in published:
                kind = artifact["kind"]
                path, metadata = store.artifact("v26_stream_owner", artifact["id"])
                receipt = verify_artifact(path, kind)
                if receipt.sha256 != metadata["sha256"]:
                    raise ValueError("Artifact receipt does not match published content")
                review = inspect_artifact(
                    path, kind,
                    bundle_receipts=bundle_receipts if kind=="zip" else None,
                    dataset_summary=summary if kind == "xlsx" else None,
                    visual_required=kind in ("pptx", "docx", "pdf"))
                if not review["passed"]:
                    raise ValueError("Generated file failed independent structural QA")
                if kind == "xlsx" and not (
                        review.get("metrics", {})
                        .get("source_profile_validation", {})
                        .get("passed")):
                    raise ValueError("Profile workbook not reconciled to all source rows")
                reports[kind] = {"sha256": receipt.sha256,
                                 "size": receipt.byte_size,
                                 "inspection_checks": review["checks"]}
                observed.add(kind)
                if path.stat().st_size < 15_000_000:
                    target = out / "artifacts" / "v26_stream"
                    target.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target / path.name)
        report["formats_verified"] = sorted(observed)
        report["artifact_inspections"] = reports
        report["passed"] = (
            processed and status == "completed"
            and bool((qa.get("quality") or {}).get("passed"))
            and report["source_arithmetic_reconciled"]
            and observed == KINDS)
        return report
    except Exception as exc:
        from rizzler.work_diagnostics import failure_code, provider_http_status
        report["error_category"] = type(exc).__name__
        report["error_code"] = failure_code(exc)
        report["error_stage"] = phase
        if (status := provider_http_status(exc)) is not None:
            report["http_status"] = status
        return report
    finally:
        if previous is None:
            os.environ.pop("RIZZLER_V26_STREAM_ANALYTICS", None)
        else:
            os.environ["RIZZLER_V26_STREAM_ANALYTICS"] = previous
