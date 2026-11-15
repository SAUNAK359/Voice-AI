"""Cognitive preflight acceptance: model autonomy + independent criticism + safety.

These tests need no Gemini credentials and exercise the actual durable SQLite
checkpoint, execution graph contract, privacy and restart behavior.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from rizzler.work_preflight import (
    PreflightContractError, PreflightRejected, enabled, generate_preflight,
    validate_preflight, validate_review, verify_committed, safe_summary)
from rizzler.work_store import WorkStore, Missing, StaleLease

OWNER="preflight_owner_001"
PAYLOAD={"objective":"Analyze the uploaded synthetic financial dataset using only its rows, "
                     "prepare an executive PDF without external references.",
         "deliverables":["pdf","data_analysis"],
         "uploads":["upload_fixture"],
         "evidence_scope":"uploaded_only"}
GRAPH={"schema_version":2,"status":"ready","steps":[
    {"id":"sql_analytics","tool":"sql_analytics","depends_on":[],"thinking_level":"medium"},
    {"id":"orchestrator","tool":"orchestrator","depends_on":["sql_analytics"],
     "thinking_level":"high"},
    {"id":"pdf_visual","tool":"pdf_visual","depends_on":["orchestrator"],
     "thinking_level":"medium"},
    {"id":"quality","tool":"quality",
     "depends_on":["sql_analytics","orchestrator","pdf_visual"],
     "thinking_level":"high"}]}


def proposal(payload=PAYLOAD, graph=GRAPH):
    return {
        "understanding":{
            "goal":"Produce source-bound financial insights with a professionally structured PDF",
            "audience":"Operations executives",
            "requested_deliverables":list(payload["deliverables"]),
            "evidence_policy":"uploaded_only",
            "uploaded_dataset":bool(payload["uploads"]),
            "success_criteria":[
                "Reconcile source revenue cost and profit before reporting",
                "Deliver readable native PDF with unambiguous monetary units",
                "Never call external research providers"],
            "uncertainties":["Source CSV headers and financial units are not known yet"],
        },
        "anticipation":{
            "risks":[{"risk":"Source numbers may not reconcile",
                      "mitigation":"Calculate aggregates using the registered SQL skill"},
                     {"risk":"PDF renderer may create unreadable pages",
                      "mitigation":"Require independent output and visual inspection"}],
            "evidence_needs":["Uploaded source dataset; no other evidence is authorized"],
            "prerequisites":["Uploaded dataset must be accessible to the owner"],
            "parallelization":"Analyze dataset before synthesis, then inspect final PDF",
        },
        "plan":copy.deepcopy(graph),
        "self_evaluation":{"approved":True,"issues":[],
                           "rationale":"All requested deliverables have an authorized evidence path and QA."}
    }


APPROVE={"verdict":"approve","issues":[],
         "summary":"The proposed graph covers financial evidence, dependencies and final QA."}
REVISE={"verdict":"revise","issues":[
    "The PDF must explicitly depend on the reconciled executive synthesis."],
    "summary":"The evidence and content ordering needs a clearer dependency."}


class PreflightContracts(TestCase):
    def test_preflight_has_six_stage_intent_and_no_invented_uploads(self):
        assert validate_preflight(proposal(),PAYLOAD)["plan"]==GRAPH
        wrong=proposal()
        wrong["understanding"]["uploaded_dataset"]=False
        with self.assertRaisesRegex(PreflightContractError,"invented_or_ignored_dataset"):
            validate_preflight(wrong,PAYLOAD)

    def test_forbid_external_research_even_if_llm_claims_permission(self):
        wrong=proposal()
        wrong["understanding"]["evidence_policy"]="external_allowed"
        with self.assertRaisesRegex(PreflightContractError,"unauthorized_external_research"):
            validate_preflight(wrong,PAYLOAD)

    def test_impossible_dag_has_actionable_trusted_feedback(self):
        wrong=proposal()
        wrong["plan"]["steps"][2]["depends_on"]=[]
        with self.assertRaisesRegex(PreflightContractError,"Renderer has no evidence"):
            validate_preflight(wrong,PAYLOAD)

    def test_self_evaluation_cannot_approve_with_unresolved_issues(self):
        wrong=proposal()
        wrong["self_evaluation"]["issues"]=["Missing financial reconciliation"]
        with self.assertRaises(PreflightContractError):
            validate_preflight(wrong,PAYLOAD)
        wrong["self_evaluation"]["approved"]=False
        with self.assertRaisesRegex(PreflightContractError,"self_review_requires_revision"):
            validate_preflight(wrong,PAYLOAD)

    def test_second_reviewer_must_provide_revisable_requirements(self):
        assert validate_review(APPROVE)==APPROVE
        with self.assertRaisesRegex(PreflightContractError,"rejection_without_actionable"):
            validate_review({"verdict":"revise","issues":[],
                             "summary":"There is a defect in the planned evidence flow."})

    def test_summary_does_not_leak_original_objective_or_model_thoughts(self):
        doc=verify_committed({**proposal(),"contract_version":1,
                              "revision_count":0,"independent_review":APPROVE},PAYLOAD)
        report=safe_summary(doc)
        assert report["status"]=="approved"
        assert "original_request" not in report
        assert "hidden_chain_of_thought" not in json.dumps(report)
        assert report["evidence_policy"]=="uploaded_only"
        assert len(report["steps"])==4

    def test_configuration_off_is_explicit(self):
        with patch.dict(os.environ,{"RIZZLER_V15_COGNITIVE_PREFLIGHT":"off"}):
            assert not enabled()
        with patch.dict(os.environ,{"RIZZLER_V15_COGNITIVE_PREFLIGHT":"on"}):
            assert enabled()


class PreflightModelCalls(IsolatedAsyncioTestCase):
    async def test_generate_with_distinct_independent_approval(self):
        mock=AsyncMock(side_effect=[proposal(),APPROVE])
        cfg=SimpleNamespace(gemini_api_key="mock",gemini_model="stub",
                            request_timeout=40)
        with patch("rizzler.work_preflight.structured_decision",new=mock):
            done=await generate_preflight(PAYLOAD,cfg)
        assert done["plan"]==GRAPH
        assert done["independent_review"]["verdict"]=="approve"
        assert mock.await_count==2
        assert "UNDERSTAND" in mock.await_args_list[0].args[0]
        assert "independent" in mock.await_args_list[1].args[0]

    async def test_independent_reviewer_revises_before_approval(self):
        mock=AsyncMock(side_effect=[proposal(),REVISE,proposal(),APPROVE])
        cfg=SimpleNamespace(gemini_api_key="mock",gemini_model="stub",
                            request_timeout=40)
        with patch("rizzler.work_preflight.structured_decision",new=mock):
            record=await generate_preflight(PAYLOAD,cfg)
        assert record["revision_count"]==1
        assert "Independent reviewer:" in mock.await_args_list[2].args[0]

    async def test_invalid_dag_is_repaired_using_precise_validation_reason(self):
        bad=proposal()
        bad["plan"]["steps"][2]["depends_on"]=[]
        mock=AsyncMock(side_effect=[bad,proposal(),APPROVE])
        cfg=SimpleNamespace(gemini_api_key="mock",gemini_model="stub",
                            request_timeout=40)
        with patch("rizzler.work_preflight.structured_decision",new=mock):
            record=await generate_preflight(PAYLOAD,cfg)
        assert record["revision_count"]==1
        assert "Renderer has no evidence or content predecessor" in mock.await_args_list[1].args[0]

    async def test_review_exhaustion_fails_closed_no_template_fallback(self):
        mock=AsyncMock(return_value=proposal())
        cfg=SimpleNamespace(gemini_api_key="mock",gemini_model="stub",
                            request_timeout=40)
        with patch("rizzler.work_preflight.structured_decision",new=mock):
            with self.assertRaises(PreflightRejected):
                await generate_preflight(PAYLOAD,cfg)
        assert mock.await_count==6

    async def test_owner_scoped_fenced_restart_reuses_approved_preflight(self):
        from rizzler import work_dynamic
        mock=AsyncMock(side_effect=[proposal(),APPROVE])
        cfg=SimpleNamespace(gemini_api_key="mock",gemini_model="stub",
                            request_timeout=40)
        with TemporaryDirectory() as root, \
             patch.dict(os.environ,{"RIZZLER_AGENTIC_ENABLED":"1",
                 "RIZZLER_V15_COGNITIVE_PREFLIGHT":"on"}), \
             patch("rizzler.work_preflight.structured_decision",new=mock):
            store=WorkStore(root)
            upload=store.register_upload(OWNER,"finance.csv",
                b"Region,Revenue_INR,Cost_INR\nEast,200,100\nWest,120,80\n")
            job=store.submit(OWNER,PAYLOAD["objective"],PAYLOAD["deliverables"],
                             "cognitive_acceptance_0001",[upload["id"]],
                             evidence_scope="uploaded_only")
            claim=store.claim("worker_a",lease_seconds=60)
            actual={**claim["payload"],
                    "_cognitive_checkpoint":(store,OWNER,claim["id"],"worker_a",claim["fence"])}
            first=await work_dynamic.generate(actual,cfg,client=object())
            assert first==GRAPH
            assert mock.await_count==2
            with self.assertRaises(Missing):
                store.cognitive_preflight("another_owner",job["id"])
            original=store.cognitive_preflight(OWNER,job["id"])
            assert original["plan"]==GRAPH
            second=await work_dynamic.generate(actual,cfg,client=object())
            assert second==GRAPH
            assert mock.await_count==2
            stored=store.install_dynamic_graph(OWNER,job["id"],"worker_a",
                                               claim["fence"],first)
            assert stored==GRAPH
            assert store.job_plan(OWNER,job["id"])==GRAPH
            with store._tx() as db:
                db.execute("UPDATE cognitive_preflights SET record_json='{}' WHERE job_id=?",
                           (job["id"],))
            with self.assertRaisesRegex(ValueError,"checksum"):
                store.cognitive_preflight(OWNER,job["id"])
