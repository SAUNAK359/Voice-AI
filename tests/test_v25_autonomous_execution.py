"""V25 genuine integration contracts: incremental source-bound checkpoints and
multi-format model-owned repair decisions, runnable without Gemini/network.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_ir import compile_ir
from rizzler.work_incremental_studio import (
    ComponentPlanError,validate_component_plan,
    create_incremental_storyboard,_cache_file,_read_chunk)
from rizzler.work_execution_recovery import (
    validate_recovery_decision,RecoveryExhausted,
    enforce_bounded_recovery,recovery_diagnostic,
    raise_verified_backdelegation)
from rizzler.work_repair import StoryboardQualificationError
from rizzler.work_studio import validate_storyboard
from rizzler.work_feedback import EvidenceGap


def sample_ir():
    return compile_ir(
        "A source-grounded architecture evaluation",
        "# Introduction\nThe architecture evaluation examines provenance and task objectives in detail.\n"
        "## Evidence\nThe verified source describes supported capabilities and the scope of the evaluation.\n"
        "## Methods\nIndependent validation is required for each output artifact before acceptance.\n"
        "## Risks\nThe deployment plan must disclose incomplete or unsupported evidence.",
        ["https://example.org/verified_source"])


def slide(local_id):
    return {
        "title":"Verified component narrative",
        "message":"Independent evidence is central to the architectural decision.",
        "kind":"evidence",
        "bullets":["Research findings retain the original verified source reference.",
                   "Missing numerical facts must not be invented or silently generalized."],
        "section_ids":[local_id],
        "source_urls":["https://example.org/verified_source"]
    }


class ComponentPlanningContracts(unittest.TestCase):
    def test_model_must_partition_original_sections_once_without_extra_sources(self):
        good={"schema_version":1,"mode":"incremental",
              "chunks":[{"section_ids":[0,1]},{"section_ids":[2,3]}],
              "reason":"Separate the evidence from the deployment assessment."}
        self.assertEqual(validate_component_plan(good,4),good)
        for bad in [
            dict(good,chunks=[{"section_ids":[0,2]},{"section_ids":[1,3]}]),
            dict(good,chunks=[{"section_ids":[0,1]},{"section_ids":[1,3]}]),
            dict(good,chunks=[{"section_ids":[0,1]},{"section_ids":[2,4]}]),
            dict(good,chunks=[{"section_ids":[0,1]},{"section_ids":[2]}]),
            dict(good,mode="single_pass"),
            dict(good,extra="unauthorized"),
        ]:
            with self.subTest(bad=bad),self.assertRaises(ComponentPlanError):
                validate_component_plan(bad,4)

    def test_small_slide_unit_can_pass_local_but_not_full_deck_coverage(self):
        ir=sample_ir()
        partial={"schema_version":1,"slides":[slide(0)]}
        valid=validate_storyboard(partial,ir.sections[:1],ir.sources,
                                  min_slides=1,max_slides=6)
        self.assertEqual(valid["sections_covered"],[0])
        with self.assertRaises(ValueError):
            validate_storyboard(partial,ir.sections,ir.sources)

    def test_local_component_cache_rejects_tampering_and_stale_provenance(self):
        ir=sample_ir()
        from rizzler.work_incremental_studio import _commit_chunk
        with TemporaryDirectory() as root:
            directory=Path(root)
            key=hashlib.sha256(b"source_model_chunk").hexdigest()
            path=_cache_file(directory,key)
            valid=validate_storyboard(
                {"schema_version":1,"slides":[slide(0)]},
                ir.sections[:1],ir.sources,
                min_slides=1,max_slides=6)
            _commit_chunk(path,key,valid)
            self.assertEqual(_read_chunk(
                path,key,ir,(0,),min_slides=1,max_slides=6),valid)
            record=json.loads(path.read_text())
            record["data"]["slides"][0]["source_urls"]=[
                "https://fabricated.invalid"]
            path.write_text(json.dumps(record),encoding="utf-8")
            self.assertIsNone(_read_chunk(
                path,key,ir,(0,),min_slides=1,max_slides=6))


class IncrementalStudioExecution(unittest.IsolatedAsyncioTestCase):
    async def test_two_independent_batched_generations_reuse_prior_qualified_chunks(self):
        ir=sample_ir()
        calls=[]
        async def fake_create(obj,local,**kwargs):
            calls.append(tuple(x[0] for x in local.sections))
            return validate_storyboard({
                "schema_version":1,
                "slides":[slide(i) for i in range(len(local.sections))]
            },local.sections,local.sources,
            min_slides=kwargs["min_slides"],
            max_slides=kwargs["max_slides"])
        plan={"schema_version":1,"mode":"incremental",
              "chunks":[{"section_ids":[0,1]},
                        {"section_ids":[2,3]}],
              "reason":"Evidence and methodology require independent reviews."}
        events=[]
        with TemporaryDirectory() as root:
            with patch("rizzler.work_incremental_studio.plan_slide_components",
                       new=AsyncMock(return_value=plan)),patch(
                       "rizzler.work_studio.create_storyboard",new=fake_create):
                output=await create_incremental_storyboard(
                    "Investigate evidence and source architecture",
                    ir,model="stub",api_key="test_key",client=object(),
                    checkpoint=Path(root),progress=events.append)
                self.assertEqual(output["sections_covered"],[0,1,2,3])
                self.assertEqual(len(output["slides"]),4)
                self.assertEqual(len(calls),2)
                again=await create_incremental_storyboard(
                    "Investigate evidence and source architecture",
                    ir,model="stub",api_key="test_key",client=object(),
                    checkpoint=Path(root),progress=events.append)
                self.assertEqual(again,output)
                self.assertEqual(len(calls),2)
                self.assertEqual(sum(x.get("status")=="reused_verified"
                                     for x in events),2)


class RecoveryAuthorizationContracts(unittest.TestCase):
    def test_model_driven_action_may_replan_only_domain_approved_formats(self):
        good={"action":"replan","reason":"The final slide blueprint needs a new section grouping.",
              "request":None}
        self.assertEqual(validate_recovery_decision(
            good,kind="pptx",permitted=frozenset({"research"})),good)
        with self.assertRaises(ValueError):
            validate_recovery_decision(
                good,kind="json",permitted=frozenset({"research"}))
        with self.assertRaises(ValueError):
            validate_recovery_decision(
                dict(good,request={"recipient":"research"}),
                kind="pptx",permitted=frozenset({"research"}))

    def test_new_specialist_permissions_are_rejected(self):
        decision={"action":"backdelegate",
                  "reason":"An independently published source measurement is needed.",
                  "request":{
                      "recipient":"sql_analytics",
                      "question":"Compute the missing annual balance using SQL",
                      "reason":"The requested chart requires verified totals.",
                      "blocking":True}}
        with self.assertRaises(ValueError):
            validate_recovery_decision(
                decision,kind="pptx",permitted=frozenset({"research"}))
        approved=validate_recovery_decision(
            decision,kind="pptx",
            permitted=frozenset({"sql_analytics"}))
        with self.assertRaises(EvidenceGap):
            raise_verified_backdelegation(
                approved,specialist="powerpoint",
                permitted=frozenset({"sql_analytics"}))

    def test_cognitive_recovery_has_explicit_attempt_budget(self):
        history=[{"action":"replan"},{"action":"rerender"},{"action":"replan"}]
        with self.assertRaises(RecoveryExhausted):
            enforce_bounded_recovery(history,{"action":"rerender"},
                                     max_attempts=3)

    def test_diagnostics_are_typed_not_raw_model_responses(self):
        error=StoryboardQualificationError("invalid_bullets")
        report=recovery_diagnostic(
            error,stage="planning",kind="pptx",attempt=1)
        self.assertEqual(report["kind"],"pptx")
        self.assertEqual(report["error_code"],"powerpoint_invalid_bullets")
        self.assertEqual(report["reason"],"invalid_bullets")
        self.assertNotIn("model_response",report)


if __name__=="__main__":
    unittest.main()
