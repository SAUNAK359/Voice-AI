#!/usr/bin/env python3
"""MVP acceptance: run actual Work ledger, specialists and artifact publication.

LIVE mode uses configured providers; offline mode uses clearly labeled fixtures
and disables semantic/model calls. All failures, skipped deliverables and
resource limitations remain visible in an inspectable evidence ZIP.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import zipfile

from rizzler.work_store import WorkStore
from rizzler.work_worker import WorkWorker
from rizzler.work_readiness import assess

OWNER="mvp_acceptance_owner"
DATA=("Region,Product,Revenue_INR,Cost_INR,Gross_Profit_INR\n"
      "North,Sensors,2400,1400,1000\n"
      "South,Sensors,2100,1300,800\n"
      "North,Controllers,1900,1100,800\n"
      "South,Controllers,1200,400,800\n").encode()
OFFLINE_TEXT=(
    "# Business operations report\n\n"
    "## Executive summary\n"
    "Four synthetic source rows show revenue of INR 7,600 and cost of INR 4,200, "
    "with gross profit of INR 3,400. These numbers must not be presented as live facts.\n\n"
    "## Financial methodology\n"
    "Revenue, cost, and gross profit are read from the exact uploaded dataset. "
    "Every source row must reconcile before interpreting metrics.\n\n"
    "## Regional and product comparisons\n"
    "| Region | Revenue INR | Gross profit INR |\n"
    "| --- | ---: | ---: |\n"
    "| North | 4300 | 1800 |\n"
    "| South | 3300 | 1600 |\n\n"
    "## Source caveats\n"
    "This is a synthetic offline fixture, not an externally verified study. "
    "Source quantities and units are preserved as supplied.\n\n"
    "## Recommendations\n"
    "Examine regional and product differences using the uploaded records, "
    "and seek independently sourced context before business decisions."
)


def offline_graph(payload):
    from rizzler.work_agents import SPECS
    requested=set(payload["deliverables"])
    steps=[]
    def add(name,deps):
        steps.append({"id":name,"tool":name,"depends_on":deps,
                      "thinking_level":"medium"})
    evidence=[]
    if payload.get("uploads"):
        add("sql_analytics",[]);evidence.append("sql_analytics")
    if "research" in requested:
        add("research",[]);evidence.append("research")
    add("orchestrator",evidence)
    render=[]
    for name in ("word","excel","powerpoint"):
        if requested.intersection(SPECS[name].formats):
            add(name,["orchestrator"]);render.append(name)
    if requested.intersection(SPECS["pdf_visual"].formats):
        add("pdf_visual",["orchestrator"]+render if "zip" in requested else ["orchestrator"])
        render.append("pdf_visual")
    add("quality",evidence+["orchestrator"]+render)
    return {"schema_version":2,"status":"ready","steps":steps}


async def complete_job(store, *, offline: bool, payload: dict, key: str):
    import unittest.mock
    job=store.submit(OWNER,payload["objective"],payload["deliverables"],key,
                     payload.get("uploads",[]),evidence_scope=payload.get("evidence_scope","auto"))
    if offline:
        async def planning(payload,*args,**kwargs):
            return offline_graph(payload)
        async def content(*args,**kwargs):
            return OFFLINE_TEXT
        async def research(*args,**kwargs):
            return {"text":OFFLINE_TEXT,"sources":[],
                    "partial":False,
                    "evidence_summary":{"provenance":"offline synthetic fixture"}}
        with unittest.mock.patch("rizzler.work_dynamic.generate",new=planning):
            await WorkWorker(store,composer=content,researcher=research).once()
    else:
        await WorkWorker(store).once()
    current=store.get(OWNER,job["id"])
    evidence={"job":current,"steps":store.agent_steps(OWNER,job["id"]),
              "events":store.events(OWNER,job["id"]),
              "plan":store.job_plan(OWNER,job["id"]),
              "artifacts":[]}
    try:
        approved=store.cognitive_preflight(OWNER,job["id"])
        if approved is not None:
            from rizzler.work_preflight import safe_summary
            evidence["cognitive"]=safe_summary(approved)
    except (ValueError,KeyError) as exc:
        evidence["cognitive_integrity_error"]=type(exc).__name__
    if current["status"]=="completed":
        evidence["quality"]=store.quality_report(OWNER,job["id"])
        for item in store.artifacts(OWNER,job["id"]):
            path,_=store.artifact(OWNER,item["id"])
            evidence["artifacts"].append({**item,"path":str(path),
                  "sha256_verified":hashlib.sha256(path.read_bytes()).hexdigest()==item["sha256"]})
    return evidence


async def run(output: Path, offline: bool) -> dict:
    output.mkdir(parents=True,exist_ok=True)
    old=os.environ.copy()
    if offline:
        os.environ.update({
            "RIZZLER_AGENTIC_ENABLED":"1",
            "RIZZLER_V15_COGNITIVE_PREFLIGHT":"off",
            "RIZZLER_V15_PRESENTATION":"0",
            "RIZZLER_V15_RECOVERY":"0",
            "RIZZLER_ARTIFACT_QA":"structural",
        })
    try:
        system=assess()
        store=WorkStore(output/"runtime")
        upload=store.register_upload(OWNER,"synthetic_finance.csv",DATA)
        data_job={"objective":"Create a complete source-only financial executive package, "
                              "preserving INR and every original dataset value.",
                  "deliverables":["data_analysis","pptx","docx","xlsx","pdf","md","zip"],
                  "uploads":[upload["id"]],"evidence_scope":"uploaded_only"}
        research_job={"objective":"Investigate the latest official Indian international trade "
                                  "statistics, reconcile fiscal-year periods and currencies, "
                                  "cite attributed sources and create an editable presentation "
                                  "plus a PDF and Markdown briefing.",
                      "deliverables":["research","pptx","pdf","md"],
                      "uploads":[],"evidence_scope":"external_allowed"}
        cases=[("finance_multi_format",data_job),("trade_research_to_presentation",research_job)]
        results=[]
        for name,payload in cases:
            key="acceptance_"+secrets.token_hex(12)
            item=await complete_job(store,offline=offline,payload=payload,key=key)
            item["scenario"]=name
            item["requested_formats"]=payload["deliverables"]
            item["published_formats"]=[x["kind"] for x in item["artifacts"]]
            item["published_complete"]=(item["job"]["status"]=="completed" and
               set(item["published_formats"]) ==
               set(payload["deliverables"]) -
               {"research","data_analysis","automation_plan","task_management","voice_status"})
            for artifact in item["artifacts"]:
                source=Path(artifact["path"])
                target=output/"published"/name/source.name
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
                artifact.pop("path")
            results.append(item)
        report={"schema_version":1,
                "mode":"offline_fixtures_no_provider_calls" if offline else "live_providers",
                "configuration":system,
                "cases":results,
                "completed":sum(x["published_complete"] for x in results),
                "total":len(results),
                "limitations":(
                    ["Offline fixtures test native execution only; do not prove model cognition, research or design quality"]
                    if offline else
                    ["Provider grounding is attribution, not independently verified external source text",
                     "Human review is still required for editorial and design quality"]),
               }
        (output/"acceptance_report.json").write_text(
            json.dumps(report,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
        with zipfile.ZipFile(output/"MVP_ACCEPTANCE_REPORT.zip","w",zipfile.ZIP_DEFLATED) as archive:
            archive.write(output/"acceptance_report.json","acceptance_report.json")
            published=output/"published"
            for path in sorted(published.rglob("*")) if published.exists() else []:
                if path.is_file():
                    archive.write(path,path.relative_to(output).as_posix())
        return report
    finally:
        os.environ.clear()
        os.environ.update(old)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path("mvp_acceptance"))
    parser.add_argument("--offline",action="store_true",
                        help="Run verifiable synthetic fixtures without model calls")
    args=parser.parse_args()
    report=asyncio.run(run(args.output.resolve(),args.offline))
    print(json.dumps({"completed":report["completed"],"total":report["total"],
        "mode":report["mode"],
        "cases":[{"scenario":x["scenario"],"status":x["job"]["status"],
                  "error_code":x["job"].get("error_code"),
                  "published_formats":x["published_formats"]}
                 for x in report["cases"]]},indent=2))
    print("Report:",(args.output/"MVP_ACCEPTANCE_REPORT.zip").resolve())
    return 0 if report["completed"]==report["total"] else 1


if __name__=="__main__":
    raise SystemExit(main())
