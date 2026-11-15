"""V15 offline contract tests: model decisions, independent critique and recovery."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import unittest

from rizzler.v15_agentic import (
    V15Unavailable, V15QualityError, enabled, plan, improve_draft,
    validate_decision, recoverable, error_code,
)
from rizzler.v15_research import research
from rizzler.work_store import WorkStore


class StubModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    async def complete(self, instructions, content, **kwargs):
        self.requests.append((instructions, content, kwargs))
        return self.replies.pop(0)


def test_v15_flag_defaults_to_off_and_canary_is_explicit(monkeypatch):
    monkeypatch.delenv("RIZZLER_V15_MODE", raising=False)
    assert not enabled("v15")
    monkeypatch.setenv("RIZZLER_V15_MODE", "canary")
    assert enabled("v15")
    assert not enabled()
    monkeypatch.setenv("RIZZLER_V15_MODE", "on")
    assert enabled()
    assert enabled("legacy")


def test_v15_llm_scope_not_keyword_based():
    model = StubModel([{"research":True, "analysis":False,
                        "reason":"This task requires external economic evidence."}])
    result = asyncio.run(plan("Build a deck showing the actual economic picture.",
                              ["pptx"], [], model=model))
    assert result["research"] is True
    assert len(model.requests) == 1
    assert "objective" in model.requests[0][1]
    assert validate_decision(result, []) == result


def test_v15_scope_rejects_unauthorized_analysis():
    with unittest.TestCase().assertRaises(V15Unavailable):
        validate_decision({"research":True, "analysis":True,
                           "reason":"Please analyze a nonexistent upload."}, [])


def test_independent_critique_revisions_are_bounded():
    stub = StubModel([
        {"verdict":"revise", "feedback":"Specify the unit and evidence limits."},
        "# Revised brief\n\nVerified facts are limited to the supplied evidence.",
        {"verdict":"pass", "feedback":"The draft now states its limitations."}
    ])
    result, audit = asyncio.run(improve_draft(
        "Prepare evidence brief", "# Original\n\nWeak draft.",
        ["https://example.org/data"], None, model=stub))
    assert "Revised" in result
    assert audit["status"] == "pass"
    assert audit["rounds"] == 2
    assert len(stub.requests) == 3


def test_independent_critique_rejection_fails_closed():
    stub = StubModel([{"verdict":"reject",
                       "feedback":"Unverifiable figures cannot be published."}])
    with unittest.TestCase().assertRaises(V15QualityError):
        asyncio.run(improve_draft("Report", "Invented evidence", [], None,
                                  model=stub))
    assert error_code(V15QualityError("bad")) == "v15_quality_rejected"
    assert recoverable(TimeoutError("transport"))


def test_v15_research_requires_independently_fetched_pages():
    async def discovery(_objective):
        return {"sources":["https://example.org/report", "http://127.0.0.1/private"],
                "text":"This is provider attribution, not independently verified evidence."}

    async def fetcher(url):
        return {"url":url, "excerpt":"Verified public economics page. " * 20,
                "sha256":"a"*64, "fetched_at":100.,
                "content_type":"text/plain", "bytes":2000}

    model = StubModel(["# Findings\n\nThe source is limited and must be validated."])
    output = asyncio.run(research("Summarize exports", discovery,
                                  model=model, fetcher=fetcher))
    assert len(output["sources"]) == 1
    assert output["evidence"][0]["content_verified"] is True
    assert output["evidence_summary"]["source_document_fetch"] is True
    assert "127.0.0.1" not in model.requests[0][1]


def test_v15_job_plan_has_research_without_explicit_research_format():
    with tempfile.TemporaryDirectory() as root:
        store=WorkStore(root)
        job=store.submit("test_owner_01", "Prepare a factual trade deck",
                         ["pptx"], "v15_idem_0001", [],
                         v15={"research":True, "analysis":False,
                              "reason":"External trade statistics are required."})
        graph=store.job_plan("test_owner_01", job["id"])
        assert [step["id"] for step in graph["steps"]] == [
            "research", "powerpoint", "quality"]
        assert store.submit("test_owner_01", "Prepare a factual trade deck",
                            ["pptx"], "v15_idem_0001", [],
                            v15={"research":False, "analysis":False,
                                 "reason":"Changed model decision."})["id"] == job["id"]


def test_v15_transient_retry_keeps_job_and_backoff():
    with tempfile.TemporaryDirectory() as root:
        store=WorkStore(root)
        job=store.submit("test_owner_01", "Prepare a factual trade deck",
                         ["pptx"], "v15_idem_0002", [],
                         v15={"research":True, "analysis":False,
                              "reason":"External trade statistics are required."})
        claim=store.claim("worker_one",lease_seconds=45)
        assert claim["id"] == job["id"]
        assert store.retry(job["id"],"worker_one",claim["fence"]) is True
        assert store.get("test_owner_01",job["id"])["status"]=="queued"
        assert store.claim("worker_two",lease_seconds=45) is None
        with store._tx() as db:
            db.execute("UPDATE jobs SET lease_until=0 WHERE id=?",(job["id"],))
        new_claim=store.claim("worker_two",lease_seconds=45)
        assert new_claim["fence"] > claim["fence"]
        assert new_claim["payload"]["v15"]["research"] is True
