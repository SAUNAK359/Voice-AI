"""Offline integration tests for the shared V12 agent control plane."""
import asyncio
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from rizzler.agent_runtime import AgentRuntime, discover, check_args
from rizzler.config import Settings
from rizzler.work_store import WorkStore, Missing, Conflict


def settings():
    return Settings(access_key="v12-tests-access-secret-123456",gemini_api_key="not-a-real-api-key")


class DirectedRuntime(AgentRuntime):
    def __init__(self, store, decisions):
        super().__init__(store,settings(),client=SimpleNamespace(aio=SimpleNamespace()))
        self.decisions=list(decisions)

    async def decide(self,client,state,tools):
        return self.decisions.pop(0)


def call(name,**kwargs):
    return {"calls":[{"name":name,"arguments":kwargs}],"answer":""}


def final(answer):
    return {"calls":[],"answer":answer}


def test_dynamic_catalog_reflects_installed_services(tmp_path):
    assert "work.submit" not in discover(None)
    store=WorkStore(tmp_path/"work")
    catalog=discover(store)
    assert "work.submit" in catalog and "work.lineage" in catalog
    assert "work.cancel" in catalog and catalog["work.cancel"].effect=="confirm"
    with pytest.raises(ValueError):
        check_args({"deliverables":["pdf","pdf"]},catalog["work.submit"].schema)
    with pytest.raises(ValueError):
        check_args({"deliverables":["delete_database"]},catalog["work.submit"].schema)


def test_model_directed_work_is_queued_and_shared(tmp_path):
    store=WorkStore(tmp_path/"work")
    agent=DirectedRuntime(store,[call("work.submit",deliverables=["pdf","pptx"]),
                                call("work.list"),final("The requested job is queued.")])
    result=asyncio.run(agent.run("Compile a robotics overview with a PDF and slides",
                                "owner_one",nonce="session",sequence=2))
    jobs=store.list_jobs("owner_one")
    assert len(jobs)==1 and jobs[0]["status"]=="queued"
    assert result["job"]["id"]==jobs[0]["id"]
    assert len(store.job_plan("owner_one",jobs[0]["id"])["steps"])>=3
    assert store.list_jobs("owner_two")==[]


def test_confirmation_gate_owner_isolation_and_revision_lineage(tmp_path):
    store=WorkStore(tmp_path/"work")
    source=store.submit("owner_one","Create a PDF on robotics",["pdf"],"source_job_001")
    agent=DirectedRuntime(store,[call("work.revise",job_id=source["id"],
              objective="Create an updated robotics presentation",deliverables=["pptx"])])
    result=asyncio.run(agent.run("Revise my existing robotics report to use slides",
                                "owner_one",nonce="a",sequence=1))
    approval=result["approvals"][0]
    assert len(store.list_jobs("owner_one"))==1
    with pytest.raises(Missing):
        store.confirm_agent_action("other_user",approval["id"])
    revision=store.confirm_agent_action("owner_one",approval["id"])
    assert revision["status"]=="queued"
    assert store.confirm_agent_action("owner_one",approval["id"])["id"]==revision["id"]
    assert store.lineage("owner_one",revision["id"])["parents"][0]["parent_id"]==source["id"]
    assert store.get("owner_one",source["id"])["status"]=="queued"
    with pytest.raises(Missing):
        store.lineage("other_user",revision["id"])


def test_cancellation_is_not_executed_by_model(tmp_path):
    store=WorkStore(tmp_path/"work")
    job=store.submit("owner_one","Make a useful report",["pdf"],"cancel_job_001")
    agent=DirectedRuntime(store,[call("work.cancel",job_id=job["id"])])
    result=asyncio.run(agent.run("Cancel that report","owner_one"))
    assert store.get("owner_one",job["id"])["status"]=="queued"
    store.confirm_agent_action("owner_one",result["approvals"][0]["id"])
    assert store.get("owner_one",job["id"])["status"]=="cancelled"


def test_repeated_modifying_decisions_fail_closed(tmp_path):
    store=WorkStore(tmp_path/"work")
    agent=DirectedRuntime(store,[
        call("work.submit",deliverables=["pdf"]),
        call("work.submit",deliverables=["pptx"]),
    ])
    result=asyncio.run(agent.run("Create a report","owner_one",nonce="run",sequence=9))
    assert len(store.list_jobs("owner_one"))==1
    assert result["verified"] is False


def test_provider_selected_read_only_tools_can_run_concurrently(tmp_path):
    store=WorkStore(tmp_path/"work")
    job=store.submit("owner_one","Make a report",["pdf"],"read_job_001")
    agent=DirectedRuntime(store,[{"calls":[
        {"name":"work.status","arguments":{"job_id":job["id"]}},
        {"name":"work.plan","arguments":{"job_id":job["id"]}},
    ],"answer":""},final("Both checks completed.")])
    result=asyncio.run(agent.run("Summarize my job and plan","owner_one"))
    assert len(result["actions"])==2 and all(x["ok"] for x in result["actions"])


def test_api_same_owner_as_voice_and_work(tmp_path,monkeypatch):
    from rizzler.api import create_app
    monkeypatch.setenv("RIZZLER_WORK_ROOT",str(tmp_path/"work"))
    monkeypatch.setenv("RIZZLER_WORK_SIGNING_KEY","v12-test-work-signing-key-long-enough-1234")
    monkeypatch.setenv("RIZZLER_AGENTIC_ENABLED","1")
    async def model(self,client,state,tools):
        if any(x.get("role")=="tool_result" for x in state):
            return final("Work successfully queued; execution is independent.")
        return call("work.submit",deliverables=["pdf"])
    monkeypatch.setattr(AgentRuntime,"decide",model)
    with TestClient(create_app(settings())) as c:
        headers={"x-rizzler-key":settings().access_key,"x-session-id":"owner_test_1234"}
        res=c.post("/api/agent/turn",headers=headers,json={"text":"Produce a PDF report"})
        assert res.status_code==200,res.text
        jid=res.json()["job"]["id"]
        assert c.get("/api/voice/jobs/"+jid,headers=headers).status_code==200
        different={"x-rizzler-key":settings().access_key,"x-session-id":"another_owner_456"}
        assert c.get("/api/voice/jobs/"+jid,headers=different).status_code==404
        assert c.post("/api/agent/approvals/"+"0"*32+"/confirm",headers=different).status_code==404
