"""V12 agentic Work plan and unified Voice/Work authentication regression tests."""
from __future__ import annotations
import asyncio
import unittest

try:
    import pytest
    from fastapi.testclient import TestClient
    from rizzler.api import create_app
    from rizzler.config import Settings
    from rizzler.work_dynamic import validate, pending
    from rizzler.work_store import WorkStore, Missing
    from rizzler.work_specialists import execute_specialists
except ImportError:
    raise unittest.SkipTest("V12 Work integration requires App test extras")


OWNER="owner_agentic_001"
PDF={"objective":"Produce an evidence-based PDF market report",
     "deliverables":["pdf"],"uploads":[]}


def graph(*rows):
    return {"schema_version":2,"status":"ready",
            "steps":[{"id":name,"tool":name,"depends_on":deps}
                     for name,deps in rows]}


def test_dynamic_graph_rejects_fixed_assumptions_and_invalid_dependence():
    assert pending()["status"]=="planning"
    valid=graph(("research",[]),("pdf_visual",["research"]),
                ("quality",["research","pdf_visual"]))
    assert validate(valid,PDF)==valid
    another=graph(("orchestrator",[]),("pdf_visual",["orchestrator"]),
                  ("quality",["orchestrator","pdf_visual"]))
    assert validate(another,PDF)==another
    with pytest.raises(ValueError):
        validate(graph(("orchestrator",[]),("pdf_visual",[]),
                       ("quality",["orchestrator","pdf_visual"])),PDF)
    with pytest.raises(ValueError):
        validate(graph(("orchestrator",[]),("quality",["orchestrator"])),PDF)
    with pytest.raises(ValueError):
        validate(graph(("orchestrator",["quality"]),("pdf_visual",["orchestrator"]),
                       ("quality",["orchestrator","pdf_visual"])),PDF)


def test_new_agentic_job_persists_placeholder_and_fenced_model_graph(tmp_path,monkeypatch):
    monkeypatch.setenv("RIZZLER_AGENTIC_ENABLED","1")
    store=WorkStore(tmp_path/"work")
    job=store.submit(OWNER,PDF["objective"],PDF["deliverables"],"dynamic_plan_001",[])
    assert store.job_plan(OWNER,job["id"])==pending()
    assert store.agent_steps(OWNER,job["id"])==[]
    claim=store.claim("worker-A")
    selected=graph(("orchestrator",[]),("pdf_visual",["orchestrator"]),
                   ("quality",["orchestrator","pdf_visual"]))
    assert store.install_dynamic_graph(OWNER,job["id"],"worker-A",claim["fence"],selected)==selected
    assert store.job_plan(OWNER,job["id"])==selected
    assert len(store.agent_steps(OWNER,job["id"]))==3
    with pytest.raises(ValueError):
        store.install_dynamic_graph(OWNER,job["id"],"worker-A",claim["fence"],
            graph(("research",[]),("pdf_visual",["research"]),("quality",["research","pdf_visual"])))
    with pytest.raises(Missing):
        store.job_plan("other_agent_user",job["id"])


def test_dynamic_work_executes_actual_model_graph_not_template(tmp_path,monkeypatch):
    monkeypatch.setenv("RIZZLER_AGENTIC_ENABLED","1")
    store=WorkStore(tmp_path/"work")
    job=store.submit(OWNER,"Explain robotics trends in text",["answer"],"dynamic_job_002",[])
    claim=store.claim("worker-agent")
    from rizzler import work_dynamic
    proposed=graph(("orchestrator",[]),("quality",["orchestrator"]))
    async def fake_plan(payload, settings):
        return proposed
    async def fake_content(objective, summary):
        return "# Robotics\n\nThis is a substantive researched-style but ungrounded example briefing, not real-time evidence."
    async def fake_search(objective):
        raise AssertionError("The unselected research capability must not run")
    monkeypatch.setattr(work_dynamic,"generate",fake_plan)
    asyncio.run(execute_specialists(store,claim,"worker-agent",fake_content,fake_search))
    completed=store.get(OWNER,job["id"])
    assert completed["status"]=="completed"
    assert store.job_plan(OWNER,job["id"])==proposed
    assert [row["agent"] for row in store.agent_steps(OWNER,job["id"])]==["orchestrator","quality"]
    assert store.quality_report(OWNER,job["id"])["quality"]["passed"]


def test_no_unplanned_stage_fallback_on_missing_provider(tmp_path,monkeypatch):
    monkeypatch.setenv("RIZZLER_AGENTIC_ENABLED","1")
    store=WorkStore(tmp_path/"work")
    job=store.submit(OWNER,"Create a new PDF technical report",["pdf"],"dynamic_no_fallback_001",[])
    claim=store.claim("worker-A")
    from rizzler import work_dynamic
    async def missing_provider(*args,**kwargs):
        raise RuntimeError("provider disabled")
    monkeypatch.setattr(work_dynamic,"generate",missing_provider)
    with pytest.raises(RuntimeError):
        asyncio.run(execute_specialists(store,claim,"worker-A",None,None))
    assert store.job_plan(OWNER,job["id"])==pending()
    assert not store.agent_steps(OWNER,job["id"])


def test_demo_voice_and_work_api_require_identical_session(tmp_path,monkeypatch):
    monkeypatch.setenv("RIZZLER_WORK_ROOT",str(tmp_path/"work"))
    monkeypatch.delenv("RIZZLER_WORK_SIGNING_KEY",raising=False)
    monkeypatch.setenv("RIZZLER_AGENTIC_ENABLED","1")
    secret="strong_demo_auth_key_for_agentic_test_123"
    settings=Settings(access_key=secret)
    with TestClient(create_app(settings)) as client:
        owner={"x-rizzler-key":secret,"x-session-id":OWNER}
        other={"x-rizzler-key":secret,"x-session-id":"other_owner_001"}
        unauthorized={"authorization":"Bearer fake_work_token"}
        assert client.get("/api/work/jobs",headers=unauthorized).status_code==401
        response=client.post("/api/work/jobs",headers={
            **owner,"idempotency-key":"shared_voice_work_001"},
            json={"objective":"Produce a detailed PDF report",
                  "deliverables":["pdf"],"uploads":[]})
        assert response.status_code==202,response.text
        jid=response.json()["id"]
        assert client.get("/api/work/jobs/"+jid,headers=owner).status_code==200
        assert client.get("/api/voice/jobs/"+jid,headers=owner).status_code==200
        assert client.get("/api/work/jobs/"+jid,headers=other).status_code==404
        assert client.get("/api/work/jobs/"+jid+"/plan",headers=owner).json()==pending()
