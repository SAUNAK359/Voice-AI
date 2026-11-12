"""Durable specialist agent acceptance: plans, SQL restrictions, recovery and ownership."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import time
import unittest
from pathlib import Path

if any(importlib.util.find_spec(x) is None for x in ("pytest", "fastapi", "httpx")):
    raise unittest.SkipTest("Specialist tests run in App CI with optional dependencies")

import pytest
from fastapi.testclient import TestClient

from rizzler.config import Settings
from rizzler.api import create_app
from rizzler.providers import expressive_speech_speed, GeminiLLM
from rizzler.work_agents import SPECS, SPECIALISTS, plan, read_skill, gate_agent
from rizzler.work_store import WorkStore, Missing, StaleLease
from rizzler.work_worker import WorkWorker
from rizzler.work_sql import analyze_sql, execute_readonly_sql
from rizzler.work_auth import issue_token


KEY = "specialist-test-voice-key-12345"
SIGNING = "specialist-independent-work-signing-key-123456"


async def composer(objective, metrics):
    return "# Executive summary\nThis report contains independent verified figures and a complete analysis plan. " * 2


def test_all_six_playbooks_and_complete_plan():
    assert len(SPECIALISTS) == 6
    assert all(read_skill(name).startswith("#") for name in SPECIALISTS)
    assert {n for n in SPECS if n not in SPECIALISTS} == {"orchestrator", "quality"}
    p = plan({"deliverables": ["research", "data_analysis", "pptx", "docx",
             "xlsx", "csv", "pdf", "png", "svg", "zip", "json"], "uploads": ["id"]})
    assert [x.name for x in p] == [
        "research", "sql_analytics", "powerpoint", "word", "excel", "pdf_visual", "quality"]
    assert plan({"deliverables": ["md"], "uploads": []})[-1].name == "quality"
    with pytest.raises(ValueError):
        plan({"deliverables": ["data_analysis"], "uploads": []})
    with pytest.raises(ValueError):
        plan({"deliverables": ["md"], "uploads": ["one", "two"]})


def test_sql_is_computed_and_has_no_write_privileges(tmp_path):
    csv = tmp_path / "facts.csv"
    csv.write_text("region,amount\nNorth,10\nSouth,20\nEast,30\n", encoding="utf-8")
    result = analyze_sql(csv)
    assert result["summary"]["rows"] == result["summary"]["sql_row_count"] == 3
    assert result["summary"]["numeric"]["amount"]["mean"] == 20
    assert result["summary"]["sql_numeric_columns_verified"] == 1
    assert result["sql_verified_metrics"]["amount"]["mean"] == 20
    assert execute_readonly_sql(["a"], [["x"], ["y"]],
               "SELECT COUNT(*) FROM dataset") == [(2,)]
    assert execute_readonly_sql(["category", "amount"],
               [["North", "10"], ["South", "20"]],
               "SELECT AVG(CAST(c1 AS REAL)) FROM dataset") == [(15.0,)]
    for unsafe in ("DELETE FROM dataset", "ATTACH DATABASE '/tmp/bad' AS evil",
                   "SELECT load_extension('malicious')",
                   "SELECT * FROM sqlite_master"):
        with pytest.raises((PermissionError, ValueError, __import__("sqlite3").DatabaseError)):
            execute_readonly_sql(["a"], [["x"]], unsafe)
    with pytest.raises(ValueError):
        execute_readonly_sql(["a"], [["x"]] * 200, "SELECT * FROM dataset", max_rows=1)


def test_durable_specialist_workflow_and_cross_owner_access(tmp_path):
    root = tmp_path / "work"
    store = WorkStore(root)
    upload = store.register_upload("owner_1", "facts.csv",
                    b"category,amount\nA,10\nB,20\n")
    job = store.submit("owner_1","Produce a professional report on this dataset.",
                       ["data_analysis","md","pdf","docx","xlsx","pptx","json","zip"],
                       "specialist_job_0001", [upload["id"]])
    assert asyncio.run(WorkWorker(store, composer=composer).once())
    job = store.get("owner_1", job["id"])
    assert job["status"] == "completed", job
    states = store.agent_steps("owner_1", job["id"])
    assert {x["agent"] for x in states} == {
        "sql_analytics", "orchestrator", "powerpoint", "word", "excel",
        "pdf_visual", "quality"}
    assert all(x["status"] == "completed" for x in states)
    assert all(x["qa_json"] for x in states)
    assert len(store.artifacts("owner_1", job["id"])) == 7
    reopened = WorkStore(root)
    assert len(reopened.agent_steps("owner_1", job["id"])) == len(states)
    quality = reopened.quality_report("owner_1", job["id"])
    assert quality["quality"]["passed"]
    assert quality["quality"]["artifact_quality"]["pptx"]["metrics"]["slides"] >= 2
    assert quality["quality"]["artifact_quality"]["zip"]["metrics"]["bundled"] == 6
    with pytest.raises(Missing):
        reopened.agent_steps("owner_2", job["id"])
    with pytest.raises(Missing):
        reopened.quality_report("owner_2", job["id"])
    assert reopened.events("owner_1", job["id"])


def test_restart_reuses_completed_orchestrator_checkpoint(tmp_path, monkeypatch):
    import rizzler.work_store as module
    now=[1000.0]
    monkeypatch.setattr(module.time,"time",lambda: now[0])
    store=WorkStore(tmp_path / "durable")
    job=store.submit("owner_1","Produce a thorough stand-alone report.",
                     ["md"],"checkpoint_job_01",[])
    first=store.claim("abandoned_worker",45)
    store.agent_begin(job["id"],"abandoned_worker",first["fence"],"orchestrator",150)
    text=asyncio.run(composer("report",None))
    store.agent_complete(job["id"],"abandoned_worker",first["fence"],
                         "orchestrator",{"text":text},
                         gate_agent("orchestrator",{"text":text},{"md"}))
    now[0]+=46
    calls=[0]
    async def must_not_regenerate(obj,data):
        calls[0]+=1
        raise AssertionError("Already committed orchestrator reexecuted")
    assert asyncio.run(WorkWorker(store,composer=must_not_regenerate).once())
    assert calls==[0]
    assert store.get("owner_1",job["id"])["status"]=="completed"
    states={x["agent"]:x for x in store.agent_steps("owner_1",job["id"])}
    assert states["orchestrator"]["attempt"]==1
    assert states["quality"]["status"]=="completed"


def test_fenced_agent_completion_rejects_stale_worker(tmp_path,monkeypatch):
    import rizzler.work_store as module
    now=[1000.0]
    monkeypatch.setattr(module.time,"time",lambda:now[0])
    store=WorkStore(tmp_path / "durable")
    job=store.submit("owner_1","Produce a complete durable report.",
                     ["md"],"fencing_agent_001",[])
    old=store.claim("worker_old",10)
    store.agent_begin(job["id"],"worker_old",old["fence"],"orchestrator",150)
    now[0]+=11
    new=store.claim("worker_new",10)
    assert new["fence"]>old["fence"]
    with pytest.raises(StaleLease):
        store.agent_complete(job["id"],"worker_old",old["fence"],
                             "orchestrator",{"text":"# A substantive completed report that is long enough"},
                             {"passed":True})


def test_specialist_status_endpoint_scoped_to_owner(tmp_path,monkeypatch):
    monkeypatch.setenv("RIZZLER_WORK_ROOT",str(tmp_path/"work"))
    monkeypatch.setenv("RIZZLER_WORK_SIGNING_KEY",SIGNING)
    with TestClient(create_app(Settings(access_key=KEY))) as client:
        store=client.app.state.work
        job=store.submit("owner_1","Produce a complete research report.",
                         ["md"],"status_visible_001",[])
        a=client.get("/api/work/jobs/"+job["id"]+"/agents",
                     headers={"Authorization":"Bearer "+issue_token("owner_1",SIGNING)})
        assert a.status_code == 200
        assert {x["agent"] for x in a.json()["agents"]} == {"orchestrator", "pdf_visual", "quality"}
        assert all(x["status"] == "queued" for x in a.json()["agents"])
        b=client.get("/api/work/jobs/"+job["id"]+"/agents",
                     headers={"Authorization":"Bearer "+issue_token("owner_2",SIGNING)})
        assert b.status_code==404


def test_expressive_prosody_bounded_and_safe():
    assert 1.0 <= expressive_speech_speed("Is the analysis ready?") <= 1.24
    assert expressive_speech_speed("Excellent, it's ready!") > expressive_speech_speed("Is it done?")
    assert 1.0 <= expressive_speech_speed("A long and calm explanation of verified research evidence.") <= 1.24
    assert "never pretend to use a tool" in GeminiLLM.SYSTEM.lower()


def test_corrupted_specialist_checkpoint_is_never_published(tmp_path,monkeypatch):
    import rizzler.work_store as module
    from rizzler.artifacts import verify_artifact
    from dataclasses import asdict
    now=[1000.0]
    monkeypatch.setattr(module.time,"time",lambda:now[0])
    store=WorkStore(tmp_path/"durable")
    job=store.submit("owner_1","Produce a fully validated business report.",
                     ["md"],"tamper_test_001",[])
    old=store.claim("old_worker",45)
    text=asyncio.run(composer("report",None))
    store.agent_begin(job["id"],"old_worker",old["fence"],"orchestrator",150)
    store.agent_complete(job["id"],"old_worker",old["fence"],"orchestrator",
                         {"text":text},gate_agent("orchestrator",{"text":text},{"md"}))
    path=store.root/"checkpoints"/"owner_1"/job["id"]/"md.md"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("# Verified report\nOriginal meaningful analysis from a deterministic fixture.",
                    encoding="utf-8")
    receipt=verify_artifact(path,"md")
    result={"receipts":[asdict(receipt)]}
    store.agent_begin(job["id"],"old_worker",old["fence"],"pdf_visual",120)
    store.agent_complete(job["id"],"old_worker",old["fence"],"pdf_visual",
                         result,gate_agent("pdf_visual",result,{"md"}))
    path.write_text("# Tampered report\nSubstituted contents must never be published.",
                    encoding="utf-8")
    now[0]+=46
    assert asyncio.run(WorkWorker(store,composer=composer).once())
    assert store.get("owner_1",job["id"])["status"]=="failed"
    assert store.artifacts("owner_1",job["id"])==[]


def test_fenced_promotion_rejects_stale_native_renderer(tmp_path, monkeypatch):
    """A renderer finishing after timeout must never overwrite recovered work."""
    from rizzler.artifacts import verify_artifact
    import rizzler.work_store as module
    clock = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    store = WorkStore(tmp_path / "work")
    job = store.submit("owner_1", "Produce a comprehensive verified report.",
                       ["md"], "staging_fence_001", [])
    jid = job["id"]
    old = store.claim("old_worker", 20)
    oldpath = store.root / "attempts" / "owner_1" / jid / str(old["fence"]) / "pdf_visual" / "md.md"
    oldpath.parent.mkdir(parents=True)
    oldpath.write_text("# Stale report\nThis output belongs to an expired worker attempt.", encoding="utf-8")
    stale_receipt = verify_artifact(oldpath, "md")
    clock[0] += 21
    new = store.claim("new_worker", 20)
    path = store.root / "attempts" / "owner_1" / jid / str(new["fence"]) / "pdf_visual" / "md.md"
    path.parent.mkdir(parents=True)
    path.write_text("# New verified report\nThis output belongs to the current worker only.", encoding="utf-8")
    receipt = verify_artifact(path, "md")
    final = store.agent_publish(jid, "new_worker", new["fence"], "owner_1", path, receipt)
    with pytest.raises(StaleLease):
        store.agent_publish(jid, "old_worker", old["fence"], "owner_1", oldpath, stale_receipt)
    assert final.read_bytes() == b"# New verified report\nThis output belongs to the current worker only."
    assert oldpath.exists()


def test_terminal_parent_settles_every_pending_agent(tmp_path):
    store = WorkStore(tmp_path / "work")
    job = store.submit("owner_1", "Create an independent business report.",
                       ["docx", "md"], "terminal_agents_001", [])
    claim = store.claim("agent_worker", 30)
    store.agent_begin(job["id"], "agent_worker", claim["fence"], "orchestrator", 150)
    store.fail(job["id"], "agent_worker", claim["fence"], "execution_error")
    stages = {x["agent"]: x for x in store.agent_steps("owner_1", job["id"])}
    assert stages["orchestrator"]["status"] == "failed"
    assert stages["orchestrator"]["finished"] >= stages["orchestrator"]["started"]
    assert {x["status"] for name, x in stages.items() if name != "orchestrator"} == {"skipped"}
    assert all(x["finished"] > 0 for x in stages.values())


def test_pending_quality_is_not_published_as_final(tmp_path):
    store = WorkStore(tmp_path / "work")
    job = store.submit("owner_1", "Produce a useful standalone report.",
                       ["md"], "quality_not_yet_committed", [])
    claim = store.claim("qa_worker", 30)
    store.agent_begin(job["id"], "qa_worker", claim["fence"], "quality", 45)
    store.agent_complete(job["id"], "qa_worker", claim["fence"], "quality",
                         {"passed": True, "missing": []},
                         {"passed": True, "checks": ["test_only"]})
    state = store.quality_report("owner_1", job["id"])
    assert state["status"] == "running" and state["quality"] is None
    store.fail(job["id"], "qa_worker", claim["fence"])
    state = store.quality_report("owner_1", job["id"])
    assert state["status"] == "failed" and state["quality"] is None


def test_cancelled_before_execution_settles_agent_steps(tmp_path):
    store = WorkStore(tmp_path / "work")
    job = store.submit("owner_1", "Create a report with verified formatting.",
                       ["pptx", "pdf"], "before_execution_cancelled", [])
    store.cancel("owner_1", job["id"])
    statuses = store.agent_steps("owner_1", job["id"])
    assert statuses and all(x["status"] == "cancelled" for x in statuses)
    assert all(x["finished"] > 0 for x in statuses)
