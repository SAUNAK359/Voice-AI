#!/usr/bin/env python3
"""Paid, no-mock V25 release qualification from a standalone Python process.

Designed for Kaggle/Colab subprocess execution, not a nested Jupyter event
loop. Full Work flags remain enabled. It always writes an evidence ZIP on
handled live model/agent errors and never includes private credentials or DBs.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED


def json_save(path: Path, data):
    path.write_text(json.dumps(
        data,indent=2,ensure_ascii=False,default=str),
        encoding="utf-8")


def checksum(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1048576),b""):
            h.update(chunk)
    return h.hexdigest()


def qualified_artifacts(store,owner: str,jid: str,required: set[str],
                        public_dir: Path, *, expected: dict | None = None) -> dict:
    """Verify receipt bytes and inspect actual content, never count metadata as QA."""
    from rizzler.artifacts import verify_artifact
    result={"passed":False,"verified":[],"missing":sorted(required),"errors":[]}
    job=store.get(owner,jid)
    if job["status"]!="completed":
        result["reason"]="job_not_completed"
        return result
    actual=set()
    for record in store.artifacts(owner,jid):
        kind=record["kind"]
        try:
            path,metadata=store.artifact(owner,record["id"])
            proof=verify_artifact(path,kind)
            if (not proof.verified or proof.sha256!=record["sha256"]
                    or checksum(path)!=record["sha256"]):
                raise ValueError("Cryptographic artifact checksum mismatch")
            details={}
            if kind=="pptx":
                from pptx import Presentation
                deck=Presentation(str(path))
                if len(deck.slides)<2:
                    raise ValueError("Presentation has insufficient pages")
                details["slide_count"]=len(deck.slides)
            elif kind=="docx":
                from docx import Document
                doc=Document(str(path))
                if not any(p.text.strip() for p in doc.paragraphs):
                    raise ValueError("Empty Word report")
                details["paragraph_count"]=len(doc.paragraphs)
            elif kind=="pdf":
                import fitz
                with fitz.open(path) as pdf:
                    if len(pdf)<1:
                        raise ValueError("Empty PDF")
                    details["page_count"]=len(pdf)
            elif kind=="xlsx":
                from openpyxl import load_workbook
                book=load_workbook(path,read_only=True,data_only=False)
                try:
                    if not {"Data","Checks","Summary"}<=set(book.sheetnames):
                        raise ValueError("Workbook lacks source or QA worksheets")
                    details["sheets"]=list(book.sheetnames)
                    if expected is not None:
                        source=list(book["Data"].values)
                        fields=[str(x).casefold() for x in source[0]]
                        imports=sum(float(row[fields.index("imports")])
                                    for row in source[1:])
                        exports=sum(float(row[fields.index("exports")])
                                    for row in source[1:])
                        observed={"imports":imports,"exports":exports,
                                  "net":exports-imports}
                        if any(abs(observed[k]-expected[k])>1e-9
                               for k in expected):
                            raise ValueError("Independent synthetic data totals do not reconcile")
                        details["independent_totals"]=observed
                finally:
                    book.close()
            elif kind=="zip":
                with ZipFile(path) as package:
                    if package.testzip() is not None:
                        raise ValueError("ZIP contains corrupt members")
                    details["members"]=len(package.namelist())
            if path.stat().st_size<=20_000_000:
                folder=public_dir/jid
                folder.mkdir(parents=True,exist_ok=True)
                target=folder/path.name
                shutil.copyfile(path,target)
                details["included_for_review"]=str(target.relative_to(public_dir))
            else:
                details["included_for_review"]=False
            actual.add(kind)
            result["verified"].append({
                "kind":kind,"sha256":proof.sha256,
                "bytes":path.stat().st_size,"details":details})
        except Exception as exc:
            result["errors"].append({
                "kind":kind,"category":type(exc).__name__})
    result["missing"]=sorted(required-actual)
    result["passed"]=not result["missing"] and not result["errors"]
    return result


def job_snapshot(store,owner: str,jid: str) -> dict:
    """Read only owner-scoped, validated WorkStore diagnostic data."""
    snapshot={}
    for name,callback in (
        ("job",lambda:store.get(owner,jid)),
        ("steps",lambda:store.agent_steps(owner,jid)),
        ("diagnostics",lambda:store.diagnostics(owner,jid)),
        ("events",lambda:store.events(owner,jid)),
        ("cognitive_events",lambda:store.cognitive_events(owner,jid,limit=200)),
        ("artifacts",lambda:store.artifacts(owner,jid)),
        ("quality",lambda:store.quality_report(owner,jid))):
        try:
            snapshot[name]=callback()
        except Exception as exc:
            snapshot[name]={"unavailable_category":type(exc).__name__}
    return snapshot


async def run_one(store,owner: str,job: dict,label: str,required: set[str],
                  out: Path, *,expected=None) -> dict:
    from rizzler.work_worker import WorkWorker
    jid=job["id"]
    worker_error=None
    handled=[]
    try:
        for _ in range(4):
            status=store.get(owner,jid)["status"]
            if status!="queued":
                break
            processed=await WorkWorker(store).once()
            handled.append(bool(processed))
            if not processed:
                break
    except Exception as exc:
        worker_error=type(exc).__name__
    snapshot=job_snapshot(store,owner,jid)
    artifact_qa=qualified_artifacts(
        store,owner,jid,required,out/"artifacts",expected=expected)
    state=snapshot.get("job") or {}
    state=state if isinstance(state,dict) else {}
    complete=state.get("status")=="completed"
    report={"source_job_id":jid,"label":label,
            "worker_claims_handled":handled,
            "worker_error_category":worker_error,
            "finished":complete,
            "artifact_gate":artifact_qa,
            "passed":complete and artifact_qa["passed"],
            **snapshot}
    json_save(out/(label+"_job.json"),report)
    print(label,":",state.get("status","unknown"),
          "| requested:",sorted(required),
          "| obtained:",sorted(x["kind"] for x in artifact_qa["verified"]),
          "| QUALIFIED:",report["passed"],flush=True)
    for step in snapshot.get("steps",[]):
        if isinstance(step,dict):
            print("  ",step.get("agent"),step.get("status"),
                  step.get("error_code",""),flush=True)
    return report


def offline_tests(source: Path,out: Path) -> dict:
    tests=["test_v25_autonomous_execution.py",
           "test_v25_critical_artifact_quality.py",
           "test_v25_work_recovery_integration.py",
           "test_v24_storyboard_recovery.py",
           "test_v24_context_convergence.py",
           "test_v23_excel_studio.py"]
    env=os.environ.copy()
    for name in list(env):
        if name.startswith("RIZZLER_") or name in ("GEMINI_API_KEY","GOOGLE_API_KEY"):
            env.pop(name,None)
    env["PYTHONPATH"]=str(source/"src")
    report={}
    for name in tests:
        command=[sys.executable,"-m","unittest","discover",
                 "-s",str(source/"tests"),"-p",name,"-v"]
        try:
            process=subprocess.run(
                command,cwd=str(source),env=env,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,timeout=240,check=False)
            (out/(name+".log")).write_text(process.stdout,encoding="utf-8")
            report[name]={"passed":process.returncode==0,
                          "exit_code":process.returncode}
        except subprocess.TimeoutExpired:
            report[name]={"passed":False,"category":"test_timeout"}
        print("OFFLINE",name,report[name]["passed"],flush=True)
    json_save(out/"offline_tests.json",report)
    return report


async def run_paid(source: Path,out: Path,run_id: str) -> dict:
    from rizzler.config import Settings
    from rizzler.work_store import WorkStore
    from google import genai
    preflight={"passed":False}
    cfg=Settings.from_env()
    preflight["model"]=cfg.gemini_model
    try:
        client=genai.Client(api_key=cfg.gemini_api_key)
        try:
            rsp=client.models.generate_content(
                model=cfg.gemini_model,
                contents="Return exactly: RIZZLER_V25_LIVE_OK")
            preflight["passed"]="RIZZLER_V25_LIVE_OK" in (rsp.text or "")
            if not preflight["passed"]:
                preflight["failure_category"]="unexpected_response"
        finally:
            client.close()
    except Exception as exc:
        preflight["failure_category"]=type(exc).__name__
    json_save(out/"gemini_preflight.json",preflight)
    if not preflight["passed"]:
        print("Gemini preflight NOT QUALIFIED; live Work tasks not submitted")
        return {"preflight":preflight,"research":{"passed":False},
                "analytical":{"passed":False}}
    store=WorkStore(out/"private_workstore")
    owner="v25_kaggle_owner"
    research_objective=(
        "Investigate verified first-party Google Gemini API documentation "
        "on grounding with Google Search, URL Context, and Code Execution. "
        "Explain their documented limitations, combined use conditions, "
        "source provenance and deployment risks. Produce an expert technical "
        "PowerPoint, detailed Word report, PDF report and documented ZIP. "
        "Cite independent source bytes where available; never invent "
        "citations, compatibility limits or numeric figures.")
    first=store.submit(
        owner,research_objective,["research","pptx","docx","pdf","zip"],
        "v25_research_"+run_id,[],
        requested_formats=["pptx","docx","pdf","zip"])
    research=await run_one(
        store,owner,first,"research",{"pptx","docx","pdf","zip"},out)

    data=(
        "quarter,imports,exports,region\n"
        "Q1,125,95,North\nQ2,140,105,North\n"
        "Q3,160,117,South\nQ4,175,133,South\n").encode()
    expected={"imports":600,"exports":450,"net":-150}
    uploaded=store.register_upload(
        owner,"synthetic_trade_v25.csv",data)
    analysis_objective=(
        "Analyze the uploaded SYNTHETIC quarterly imports and exports "
        "using verified read-only SQL investigations. Calculate quarterly "
        "balances, imports, exports, net position, units and limitations. "
        "Generate editable XLSX with audited formulas, a detailed editable "
        "PowerPoint, and a ZIP. These are fictional figures, NOT actual "
        "statistics for India or any country.")
    second=store.submit(
        owner,analysis_objective,["xlsx","pptx","zip"],
        "v25_analytical_"+run_id,[uploaded["id"]],
        requested_formats=["xlsx","pptx","zip"])
    analytical=await run_one(
        store,owner,second,"analytical",{"xlsx","pptx","zip"},out,
        expected=expected)
    return {"preflight":preflight,
            "research":{"passed":research["passed"],
                        "status":research.get("job",{}).get("status")},
            "analytical":{"passed":analytical["passed"],
                          "status":analytical.get("job",{}).get("status")}}


def make_bundle(out: Path,source_sha: str) -> Path:
    target=out.parent/("Rizzler_V25_Qualification_"+source_sha[:12]+
                       "_"+out.name+".zip")
    with ZipFile(target,"w",ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob("*")):
            if not path.is_file():
                continue
            relative=path.relative_to(out)
            if (any(x.startswith(".") for x in relative.parts) or
                    any(part in ("private_workstore","private_slots") for part in relative.parts) or
                    path.suffix.lower() in (".sqlite3",".db",".key",".env")):
                continue
            if path.stat().st_size>20_000_000:
                continue
            archive.write(path,relative.as_posix())
    return target


def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    parser.add_argument("--expected-sha",required=True)
    parser.add_argument("--repo",default=".")
    parser.add_argument("--model",default="")
    args=parser.parse_args()
    source=Path(args.repo).resolve()
    out=Path(args.output).resolve()
    out.mkdir(parents=True,exist_ok=True,mode=0o700)
    sha=subprocess.check_output(
        ["git","-C",str(source),"rev-parse","HEAD"],text=True).strip()
    if sha!=args.expected_sha:
        json_save(out/"setup_failure.json",
                  {"category":"source_sha_mismatch","observed":sha,
                   "expected":args.expected_sha})
        bundle=make_bundle(out,sha)
        print("NOT QUALIFIED: mismatched source",bundle)
        return 1
    os.environ["RIZZLER_V23_MODE"]="full"
    os.environ["RIZZLER_COMPONENT_PLANNING"]="1"
    os.environ["RIZZLER_AUTONOMOUS_RECOVERY"]="1"
    os.environ["RIZZLER_CANDIDATE_QUALITY"]="1"
    os.environ["RIZZLER_CONTEXT_CONVERGENCE"]="1"
    os.environ["RIZZLER_GEMINI_NATIVE_TOOLS"]="1"
    os.environ["RIZZLER_GEMINI_ENABLE_THINKING"]="true"
    os.environ["RIZZLER_ARTIFACT_QA"]="strict"
    os.environ["RIZZLER_ACCESS_KEY"]=secrets.token_urlsafe(32)
    os.environ["RIZZLER_WORK_SIGNING_KEY"]=secrets.token_urlsafe(48)
    os.environ["RIZZLER_WORK_ROOT"]=str(out/"private_workstore")
    os.environ["RIZZLER_PROVIDER_SLOT_ROOT"]=str(out/"private_slots")
    if args.model:
        os.environ["RIZZLER_GEMINI_MODEL"]=args.model
    run_id=secrets.token_hex(7)
    result={"source_sha":sha,"run_id":run_id,
            "created_at_utc":datetime.now(timezone.utc).isoformat()}
    try:
        offline=offline_tests(source,out)
        result["offline_passed"]=all(
            r.get("passed") for r in offline.values())
        if not os.environ.get("GEMINI_API_KEY"):
            result["live_failure"]="missing_api_key"
            result["paid_result"]={"preflight":{"passed":False},
                                   "research":{"passed":False},
                                   "analytical":{"passed":False}}
        else:
            paid=asyncio.run(run_paid(source,out,run_id))
            result["paid_result"]=paid
    except Exception as exc:
        result["runner_error_category"]=type(exc).__name__
    paid=result.get("paid_result") or {}
    result["passed"]=bool(
        result.get("offline_passed") and
        paid.get("preflight",{}).get("passed") and
        paid.get("research",{}).get("passed") and
        paid.get("analytical",{}).get("passed") and
        "runner_error_category" not in result)
    result["limitations"]=(
        "Structural, content and rendered QA does not constitute independent "
        "certification of every factual claim, deployment SLA or security posture.")
    json_save(out/"QUALIFICATION.json",result)
    bundle=make_bundle(out,sha)
    print("\nFINAL:","QUALIFIED BY NOTEBOOK GATES" if result["passed"]
          else "NOT QUALIFIED",flush=True)
    print("Evidence ZIP:",bundle,flush=True)
    print("Exact source SHA:",sha,flush=True)
    return 0 if result["passed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
