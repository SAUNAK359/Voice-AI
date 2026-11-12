"""Phase 1: tool policy, bounded planning, persistent DAG, research provenance.

All tests run offline. Stubs never claim external Gemini/Colab verification.
"""
from __future__ import annotations
import asyncio
import copy
import hashlib
import importlib.util
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

def _installed(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ModuleNotFoundError, ValueError):
        return False

if not all(_installed(pkg) for pkg in ("pytest","httpx","sympy","google","google.genai")):
    raise unittest.SkipTest("Phase 1 acceptance runs with app/work extras")

import pytest
from fastapi.testclient import TestClient

from rizzler.config import Settings
from rizzler.api import create_app
from rizzler.work_store import WorkStore, Missing, Conflict
from rizzler.task_planning import execution_graph, validate_graph, propose_scope
from rizzler.tool_registry import REGISTRY, require_tool, capabilities
from rizzler.research_evidence import safe_source_url, source_records, evidence_summary
from rizzler.voice_tools import VoiceTools, classify_tool
from rizzler.work_worker import WorkWorker, grounded_research

KEY="v11-phase1-test-secret-long-enough-1234"
SIGN="v11-phase1-work-signing-secret-long-enough-1234"


def payload(formats=None, uploads=None):
    return {"objective":"Research the EV industry and build a comprehensive report.",
            "deliverables":formats or ["research","pptx","pdf"],
            "uploads":uploads or []}


def test_tool_registry_does_not_grant_external_actions():
    assert "web_search" in REGISTRY and "word" in REGISTRY
    assert all(spec.version==1 and spec.timeout_seconds>0 for spec in REGISTRY.values())
    with pytest.raises(PermissionError):
        require_tool("delete_all_files",explicit_private_write=True,allowed=frozenset(REGISTRY))
    with pytest.raises(PermissionError):
        require_tool("work_submit",explicit_private_write=False,allowed=frozenset(REGISTRY))
    with pytest.raises(PermissionError):
        require_tool("pdf_visual",explicit_private_write=True,allowed=frozenset({"research"}))
    flags=capabilities(Settings(access_key=KEY),False)
    assert next(x for x in flags if x["name"]=="web_search")["state"]=="unavailable"
    assert next(x for x in flags if x["name"]=="work_submit")["state"]=="unavailable"


@pytest.mark.parametrize("formats",[
    ["pdf"],["pptx","docx"],["research","pdf"],["research","pptx","docx","xlsx","pdf","zip"],
    ["md","json","txt"],["pptx","xlsx","png","svg","docx"],
])
def test_execution_graph_exact_and_acyclic(formats):
    graph=execution_graph(payload(formats))
    known=set()
    for step in graph["steps"]:
        assert set(step["depends_on"]).issubset(known)
        known.add(step["id"])
    assert graph["steps"][-1]["id"]=="quality"
    assert validate_graph(graph,frozenset(known))==graph


def test_graph_rejects_cycle_unknown_field_false_scope_and_contract():
    graph=execution_graph(payload(["research","pptx","pdf"]))
    allowed=frozenset(x["id"] for x in graph["steps"])
    for mutation in ("cycle","unknown","tool","version","risk","missing"):
        invalid=copy.deepcopy(graph)
        if mutation=="cycle":invalid["steps"][0]["depends_on"]=["quality"]
        if mutation=="unknown":invalid["steps"][0]["extra"]="ignore policies"
        if mutation=="tool":invalid["steps"][0]["tool"]="send_email"
        if mutation=="version":invalid["steps"][0]["version"]=42
        if mutation=="risk":invalid["steps"][0]["risk"]="read_only" if invalid["steps"][0]["risk"]!="read_only" else "private_artifact"
        if mutation=="missing":invalid["steps"].pop()
        with pytest.raises((ValueError,PermissionError)):
            validate_graph(invalid,allowed)


def test_plan_is_atomic_idempotent_integrity_checked_and_owner_scoped(tmp_path):
    store=WorkStore(tmp_path/"work")
    job=store.submit("owner_123","Research EV charging and create an editable presentation.",
                     ["research","pptx"],"v11_idempotency_123",[])
    graph=store.job_plan("owner_123",job["id"])
    assert {s["id"] for s in graph["steps"]}=={"research","powerpoint","quality"}
    assert store.submit("owner_123","Research EV charging and create an editable presentation.",
                        ["research","pptx"],"v11_idempotency_123",[])["id"]==job["id"]
    with pytest.raises(Conflict):
        store.submit("owner_123","Different requested report.",["pdf"],"v11_idempotency_123",[])
    with pytest.raises(Missing):store.job_plan("other_owner",job["id"])
    with store._tx() as con:
        row=con.execute("SELECT plan_json FROM job_plans WHERE job_id=?",(job["id"],)).fetchone()
        assert row["plan_json"]
        con.execute("UPDATE job_plans SET plan_json=? WHERE job_id=?",('{"hacked":true}',job["id"]))
    with pytest.raises(ValueError,match="integrity"):
        store.job_plan("owner_123",job["id"])


class FakePlanner:
    def __init__(self,*responses):
        self.responses=list(responses)
        self.calls=0
        self.aio=SimpleNamespace(models=self)
    async def generate_content(self,**kwargs):
        self.calls+=1
        value=self.responses.pop(0)
        if isinstance(value,BaseException):raise value
        return SimpleNamespace(text=value)


def get_cfg():
    return Settings(access_key=KEY,gemini_api_key="test-only-key")


def test_model_planner_repairs_one_malformed_response_without_untrusted_tools():
    fake=FakePlanner('{"tool":"delete_my_files"}',
                     '{"research":true,"analysis":false}')
    result=asyncio.run(propose_scope("Research competitors and make a presentation.",
                                  ["pptx"],[],get_cfg(),client=fake))
    assert result["source"]=="model_validated"
    assert result["research"] and fake.calls==2


def test_model_planner_refuses_unauthorized_expensive_search_and_falls_back():
    fake=FakePlanner('{"research":true,"analysis":false}')
    result=asyncio.run(propose_scope("Create a PowerPoint and PDF from my notes.",
                                  ["pptx","pdf"],[],get_cfg(),client=fake))
    assert result["research"] is False
    assert result["source"]=="deterministic_fallback" and fake.calls==1


def test_model_planner_timeout_and_negative_instruction_never_escalate():
    assert asyncio.run(propose_scope(
        "Create a PDF but do not research anything.",["pdf"],[],get_cfg(),
        client=FakePlanner('{"research":true,"analysis":false}')))["research"] is False
    assert asyncio.run(propose_scope(
        "Create a Word document without research.",["docx"],[],Settings(access_key=KEY)))["research"] is False
    class TimeoutPlanner:
        def __init__(self):self.aio=SimpleNamespace(models=self)
        async def generate_content(self,**kw):raise TimeoutError
    result=asyncio.run(propose_scope("Research and prepare a PDF.",["pdf"],[],get_cfg(),
                                      client=TimeoutPlanner()))
    assert result["research"] and result["source"]=="deterministic_fallback"


@pytest.mark.parametrize("url",[
    "http://public.example/a","https://127.0.0.1/","https://localhost/",
    "https://169.254.169.254/latest/meta-data","https://metadata.google.internal/",
    "https://user:secret@public.example/","https://public.example:8443/x",
    "https://public.example.test/","https://public.example/\r\nX-Forged: 1",
    "file:///etc/passwd","https://[::1]/","https://evil.com@127.0.0.1/"
])
def test_source_url_never_accepts_internal_or_unsafe_targets(url):
    assert safe_source_url(url) is None


def test_source_evidence_deduplication_and_honest_uncertainty():
    def chunk(uri,title):
        return SimpleNamespace(web=SimpleNamespace(uri=uri,title=title))
    response=SimpleNamespace(candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(
        grounding_chunks=[chunk("https://example.org/story#part","publisher"),
                          chunk("https://example.org/story","duplicate"),
                          chunk("https://localhost/admin","unsafe"),
                          chunk("https://news.example.com/facts","Fact Publisher")]))])
    records=source_records(response,at=1234)
    assert len(records)==2
    assert all(not r["content_verified"] for r in records)
    assert all(r["retrieved_at"]==1234 for r in records)
    assert evidence_summary(records)["citation_verification"]=="provider_attribution_only"


def test_voice_admits_grounded_research_and_multiple_artifacts(tmp_path):
    store=WorkStore(tmp_path/"work")
    voice=VoiceTools(store,Settings(access_key=KEY))
    phrase="Research verified industry competitors and create a PowerPoint and PDF report"
    assert classify_tool(phrase,True)=="work_submit"
    async def run():
        accepted=await voice.execute(phrase,"owner_a",sequence=1,nonce="sess01")
        assert accepted["verified"] and accepted["tool"]=="work_submit"
        with store._tx() as db:
            raw=db.execute("SELECT payload FROM jobs WHERE id=?",(accepted["job"]["id"],)).fetchone()
        assert set(json.loads(raw["payload"])["deliverables"])=={"research","pptx","pdf"}
        assert [n["id"] for n in accepted["plan"]["steps"]]==[
            "research","powerpoint","pdf_visual","quality"]
        second=await voice.execute(phrase,"owner_a",sequence=1,nonce="sess01")
        assert second["job"]["id"]==accepted["job"]["id"]
        assert store.list_jobs("another_user")==[]
        return accepted["job"]["id"]
    jid=asyncio.run(run())
    assert store.job_plan("owner_a",jid)["schema_version"]==1


def test_persisted_graph_executes_with_independent_grounded_research(tmp_path):
    store=WorkStore(tmp_path/"work")
    job=store.submit("owner_1","Research electric cars and create a Markdown briefing",
                     ["research","md"],"complete_research_001",[])
    async def research(_):
        return ("# Evidence\nA substantially grounded electric-car industry briefing "
                "containing cited observations and stated limitations.",
                ["https://example.org/primary"])
    async def composer(*_):
        raise AssertionError("No extra composer should run after research")
    assert asyncio.run(WorkWorker(store,composer=composer,researcher=research).once())
    assert store.get("owner_1",job["id"])["status"]=="completed"
    assert store.quality_report("owner_1",job["id"])["quality"]["passed"]
    assert set(s["status"] for s in store.agent_steps("owner_1",job["id"]))=={"completed"}


def test_voice_api_exposes_plan_to_owner_only(tmp_path,monkeypatch):
    monkeypatch.setenv("RIZZLER_WORK_ROOT",str(tmp_path/"work"))
    monkeypatch.setenv("RIZZLER_WORK_SIGNING_KEY",SIGN)
    with TestClient(create_app(Settings(access_key=KEY))) as client:
        job=client.app.state.work.submit(
            "session_owner_123","Create an in-depth PDF report",
            ["pdf"],"server_plan_001",[])
        headers={"x-rizzler-key":KEY,"x-session-id":"session_owner_123"}
        response=client.get("/api/voice/jobs/"+job["id"],headers=headers)
        assert response.status_code==200
        assert response.json()["plan"]["steps"][-1]["id"]=="quality"
        forbidden=client.get("/api/voice/jobs/"+job["id"],headers={
            "x-rizzler-key":KEY,"x-session-id":"other_owner_123"})
        assert forbidden.status_code==404
        catalog=client.get("/api/voice/tools",headers=headers).json()
        assert len(catalog["registry"])>=10
        assert catalog["tools"]["web_search"]=="unavailable"


def test_research_noun_and_negated_search_never_trigger_unrequested_work():
    for text in ("What do you think about the research report?",
                 "I read a fascinating research report yesterday.",
                 "Please explain the phrase research report."):
        assert classify_tool(text,True) is None
    assert classify_tool("Research the EV market and write an executive report.",True)=="work_submit"
    result=asyncio.run(propose_scope(
        "Create a report from my notes but do not search the web.",
        ["pdf"],[],Settings(access_key=KEY)))
    assert not result["research"]
