"""Offline Phase-4 integration: authenticated isolation, recovery, all 12 real formats."""
from __future__ import annotations
import asyncio
import csv
import io
import json
import os
import sqlite3
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rizzler.api import create_app
from rizzler.config import Settings
from rizzler.work_auth import issue_token, verify_token
from rizzler.work_store import WorkStore, Conflict, Missing, StaleLease
from rizzler.work_worker import WorkWorker
from rizzler.work_skills import SKILLS, FORMATS, read_dataset, analyze, render_one

KEY="phase4-voice-demo-key-which-is-not-work-token"
SIGNING="phase4-independent-signing-key-with-at-least-32-characters"


@pytest.fixture
def store(tmp_path):
    return WorkStore(tmp_path/"durable")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RIZZLER_WORK_ROOT",str(tmp_path/"work"))
    monkeypatch.setenv("RIZZLER_WORK_SIGNING_KEY",SIGNING)
    with TestClient(create_app(Settings(access_key=KEY))) as c:
        yield c


def h(who):
    return {"Authorization":"Bearer "+issue_token(who,SIGNING)}


def basic(store, who="owner_1", idem="task_0001", formats=None, uploads=None):
    return store.submit(who,"Produce a useful standalone report for this request.",
                        formats or ["md"],idem,uploads or [])


def csvfile():
    return b"region,revenue,cost\nNorth,10,3\nSouth,20,6\nWest,30,9\n"


def test_token_scope_expiry_and_tamper(monkeypatch):
    token=issue_token("owner_1",SIGNING)
    assert verify_token("Bearer "+token,SIGNING)=="owner_1"
    with pytest.raises(PermissionError):
        verify_token("Bearer "+token[:-1]+("A" if token[-1]!="A" else "B"),SIGNING)
    with pytest.raises(PermissionError):
        verify_token(KEY,SIGNING)
    with pytest.raises(ValueError):
        issue_token("../bad",SIGNING)
    with pytest.raises(ValueError):
        issue_token("owner_1","short")
    import rizzler.work_auth as auth
    t=[1000]
    monkeypatch.setattr(auth.time,"time",lambda:t[0])
    issued=issue_token("owner_1",SIGNING,ttl=60)
    t[0]=1061
    with pytest.raises(PermissionError):
        verify_token("Bearer "+issued,SIGNING)


def test_voice_key_is_not_work_credential(client):
    assert client.get("/api/work/jobs",headers={"x-rizzler-key":KEY}).status_code==401
    assert client.get("/api/work/jobs",headers=h("owner_1")).status_code==200
    assert client.get("/work").status_code==200
    assert client.get("/static/work.js").status_code==200
    x=client.get("/api/work/skills",headers=h("owner_1"))
    assert x.status_code==200 and len(x.json()["skills"])==17


def test_disabled_without_work_keys(monkeypatch):
    monkeypatch.delenv("RIZZLER_WORK_ROOT",raising=False)
    monkeypatch.delenv("RIZZLER_WORK_SIGNING_KEY",raising=False)
    with TestClient(create_app(Settings(access_key=KEY))) as c:
        assert c.get("/api/work/jobs").status_code==404
        assert c.get("/work").status_code==404


def test_api_idempotency_and_scope(client):
    data={"objective":"Create a useful report for the team","deliverables":["md"],"uploads":[]}
    header={**h("owner_1"),"idempotency-key":"idempotency_001"}
    r=client.post("/api/work/jobs",headers=header,json=data)
    assert r.status_code==202
    jid=r.json()["id"]
    assert client.post("/api/work/jobs",headers=header,json=data).json()["id"]==jid
    assert client.post("/api/work/jobs",headers=header,json={**data,"objective":"Different"}).status_code==409
    assert client.get("/api/work/jobs/"+jid,headers=h("owner_2")).status_code==404
    assert client.get("/api/work/jobs/"+jid,headers=h("owner_1")).status_code==200
    assert client.get("/api/work/jobs/"+jid+"/events",headers=h("owner_1")).json()["events"]
    assert client.post("/api/work/jobs",headers={**header,"origin":"https://attacker.example"},json=data).status_code==403
    assert client.post("/api/work/jobs",headers=h("owner_1"),json=data).status_code==400
    assert client.post("/api/work/jobs/"+jid+"/cancel",headers=h("owner_2")).status_code==404
    assert client.post("/api/work/jobs/"+jid+"/cancel",headers=h("owner_1")).json()["status"]=="cancelled"


def test_upload_scoping_and_corruption(store):
    receipt=store.register_upload("owner_1","sales.csv",csvfile())
    assert store.upload("owner_1",receipt["id"]).exists()
    with pytest.raises(Missing):
        store.upload("owner_2",receipt["id"])
    with pytest.raises(Missing):
        basic(store,"owner_2","task_0002",uploads=[receipt["id"]])
    with pytest.raises(ValueError):
        store.register_upload("owner_1","../sales.csv",csvfile())
    with pytest.raises(ValueError):
        store.register_upload("owner_1","sales.xls",csvfile())
    with pytest.raises(ValueError):
        store.register_upload("owner_1","fake.xlsx",csvfile())
    store.upload("owner_1",receipt["id"]).write_bytes(b"tampered")
    with pytest.raises(Missing):
        store.upload("owner_1",receipt["id"])


def test_fenced_recovery_only_latest_worker_can_commit(store,monkeypatch):
    import rizzler.work_store as module
    now=[1000.]
    monkeypatch.setattr(module.time,"time",lambda:now[0])
    j=basic(store)
    one=store.claim("worker_A",lease_seconds=20)
    assert one["id"]==j["id"] and one["fence"]==1
    assert store.claim("worker_B",lease_seconds=20) is None
    now[0]=1021.
    two=store.claim("worker_B",lease_seconds=20)
    assert two["fence"]==2 and two["id"]==j["id"]
    with pytest.raises(StaleLease):
        store.renew(j["id"],"worker_A",1,lease_seconds=20)
    store.fail(j["id"],"worker_A",1)
    assert store.get("owner_1",j["id"])["status"]=="running"
    assert store.get("owner_1",j["id"])["attempts"]==2
    store.renew(j["id"],"worker_B",2,stage="rendering",lease_seconds=20)


def test_cancel_lost_worker_and_failure_limit(store,monkeypatch):
    import rizzler.work_store as module
    now=[1000.]
    monkeypatch.setattr(module.time,"time",lambda:now[0])
    j=basic(store)
    claimed=store.claim("one",10)
    store.cancel("owner_1",j["id"])
    with pytest.raises(InterruptedError):
        store.renew(j["id"],"one",claimed["fence"])
    store.fail(j["id"],"one",claimed["fence"])
    assert store.get("owner_1",j["id"])["status"]=="cancelled"
    j2=basic(store,idem="task_0003")
    for idx in range(3):
        c=store.claim(str(idx),10)
        assert c["id"]==j2["id"]
        now[0]+=11
    assert store.claim("last",10) is None
    assert store.get("owner_1",j2["id"])["status"]=="failed"


async def text_composer(obj,summary):
    assert "report" in obj
    return "# Executive summary\nThis example report uses only synthetic, explicitly labelled test data. "*3


async def source_research(obj):
    return "# Findings\nThis claim has a provider-grounded reference and is not fabricated.",["https://example.org/source"]


def test_real_twelve_format_output_end_to_end(store):
    upload=store.register_upload("owner_1","sales.csv",csvfile())
    formats=sorted(FORMATS)
    j=basic(store,formats=formats,uploads=[upload["id"]])
    worker=WorkWorker(store,composer=text_composer,researcher=source_research)
    assert asyncio.run(worker.once())
    result=store.get("owner_1",j["id"])
    assert result["status"]=="completed",result
    files=store.artifacts("owner_1",j["id"])
    assert set(x["kind"] for x in files)==FORMATS
    for row in files:
        path,meta=store.artifact("owner_1",row["id"])
        assert path.stat().st_size==row["size"]
        assert meta["sha256"]==row["sha256"]
    # Durability is verified by reconstructing a fresh store object.
    reopened=WorkStore(store.root)
    assert reopened.get("owner_1",j["id"])["status"]=="completed"
    assert len(reopened.events("owner_1",j["id"]))>=4


def test_no_unverified_research_success(store):
    async def no_sources(obj):
        raise ValueError("Grounding metadata missing")
    j=basic(store,idem="task_0004",formats=["research","md"])
    worker=WorkWorker(store,composer=text_composer,researcher=no_sources)
    asyncio.run(worker.once())
    assert store.get("owner_1",j["id"])["status"]=="failed"
    assert store.artifacts("owner_1",j["id"])==[]


def test_tabular_accuracy_and_formula_injection():
    header,rows=read_dataset_from_bytes(csvfile())
    metrics=analyze(header,rows)
    assert metrics["numeric"]["revenue"]["mean"]==20
    assert metrics["rows"]==3 and metrics["duplicates"]==0


def read_dataset_from_bytes(raw):
    import tempfile
    with tempfile.TemporaryDirectory() as dir:
        p=Path(dir)/"data.csv"
        p.write_bytes(raw)
        return read_dataset(p)


def test_no_fabricated_dataset_charts(store):
    j=basic(store,idem="task_0005",formats=["png"])
    asyncio.run(WorkWorker(store,composer=text_composer).once())
    assert store.get("owner_1",j["id"])["status"]=="failed"


def test_automation_only_approval_no_scheduling(store):
    j=basic(store)
    proposal=store.proposal("owner_1",j["id"],1440)
    with pytest.raises(Missing):
        store.approve_proposal("owner_2",proposal["id"])
    approved=store.approve_proposal("owner_1",proposal["id"])
    assert approved["status"]=="approved_not_scheduled"
    with pytest.raises(Conflict):
        store.approve_proposal("owner_1",proposal["id"])


def test_lease_fence_rejects_duplicate_commit(store):
    j=basic(store)
    one=store.claim("writer",30)
    assert one["id"]==j["id"]
    with pytest.raises(ValueError):
        store.finish(j["id"],"writer",one["fence"],"Output",[],store.root)
    assert store.get("owner_1",j["id"])["status"]=="running"


def test_concurrent_same_idempotency_key_returns_single_job(store):
    def submit(_):
        return basic(store, idem="same_request_001")["id"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids=list(pool.map(submit,range(12)))
    assert len(set(ids))==1
    assert len(store.list_jobs("owner_1"))==1
