"""V20 owner isolation, draft integrity and actionable Quality classification."""
import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from rizzler.contracts import ArtifactReceipt
from rizzler.work_store import WorkStore, Missing
from rizzler.work_repair import (
    QualityReviewFailure, QualityRepairFailure, QualityValidationFailure)
from rizzler.work_cognition import failure_code


class DraftProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"RIZZLER_AGENTIC_ENABLED": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = WorkStore(Path(self.tmp.name))
        self.owner = "owner_v20"
        self.job = self.store.submit(
            self.owner, "Write a structured analysis with a Markdown report",
            ["md"], "v20-" + "x" * 20)
        self.worker = "worker_v20"
        self.claim = self.store.claim(self.worker, lease_seconds=45)
        self.jid = self.job["id"]
        graph = {"schema_version": 2, "status": "ready", "steps": [
            {"id": "orchestrator", "tool": "orchestrator", "depends_on": [],
             "thinking_level": "medium"},
            {"id": "pdf_visual", "tool": "pdf_visual",
             "depends_on": ["orchestrator"], "thinking_level": "medium"},
            {"id": "quality", "tool": "quality",
             "depends_on": ["orchestrator", "pdf_visual"],
             "thinking_level": "high"}]}
        self.store.install_dynamic_graph(
            self.owner, self.jid, self.worker, self.claim["fence"], graph)

    def test_progress_is_durable_and_validated(self):
        self.store.record_progress(
            self.jid, self.worker, self.claim["fence"],
            "quality_review", "Reviewing semantic completeness")
        events = self.store.events(self.owner, self.jid)
        self.assertTrue(any(e["stage"] == "quality_review" for e in events))
        with self.assertRaises(ValueError):
            self.store.record_progress(
                self.jid, self.worker, self.claim["fence"],
                "quality_review", "secret\nleak")
        with self.assertRaises(ValueError):
            self.store.record_progress(
                self.jid, self.worker, self.claim["fence"],
                "unauthorized", "Not allowed")

    def test_owner_only_draft_is_checksum_verified_and_unpublished(self):
        data = b"# Draft analysis\n\nThis report has yet to pass final QA.\n" * 5
        directory = self.store.root / "checkpoints" / self.owner / self.jid
        directory.mkdir(parents=True)
        artifact = directory / "md.md"
        artifact.write_bytes(data)
        receipt = ArtifactReceipt(
            kind="md", name="md.md", sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data), verified=True).validate()
        self.store.agent_begin(
            self.jid, self.worker, self.claim["fence"], "pdf_visual", 120)
        self.store.agent_complete(
            self.jid, self.worker, self.claim["fence"], "pdf_visual",
            {"receipts": [asdict(receipt)]}, {"passed": True})
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from rizzler.work_api import router
        except ImportError:
            FastAPI = None
        if FastAPI is not None:
            app = FastAPI()
            app.include_router(router(self.store, owner_resolver=lambda req: self.owner))
            with TestClient(app) as client:
                    listing = client.get(f"/api/work/jobs/{self.jid}/drafts")
                    self.assertEqual(listing.status_code, 200)
                    self.assertFalse(listing.json()["verified_final"])
                    self.assertEqual([x["kind"] for x in listing.json()["artifacts"]], ["md"])
                    response = client.get(f"/api/work/jobs/{self.jid}/drafts/md")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.content, data)
                    self.assertEqual(response.headers["x-rizzler-artifact-status"],
                                 "draft-unverified")
        with self.assertRaises(Missing):
            self.store.drafts("another_owner", self.jid)
        artifact.write_bytes(b"corrupted")
        self.assertEqual(self.store.drafts(self.owner, self.jid), [])
        self.assertEqual(self.store.draft_text(self.owner, self.jid)["status"], "pending")

    def test_quality_errors_have_distinct_categories(self):
        self.assertEqual(failure_code(QualityReviewFailure("review_failed")),
                         "quality_review_failed")
        self.assertEqual(failure_code(QualityRepairFailure("repair_failed")),
                         "quality_repair_failed")
        self.assertEqual(failure_code(QualityValidationFailure("validation_failed")),
                         "quality_validation_failed")


class EditorialBlueprintTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_authored_sections_are_validated_without_network(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from rizzler.work_editorial import validate, as_instruction, plan_editorial
        from rizzler.work_cognition import CognitiveDecisionError
        draft = {
            "audience": "Technical stakeholders",
            "core_question": "How should the system improve substantive reports?",
            "editorial_depth": "comprehensive",
            "sections": [
                {"heading": "Architecture decisions",
                 "purpose": "Explain causal mechanisms",
                 "evidence_or_assumptions": "Repository design and explicit assumptions",
                 "specific_analysis": "Compare alternative orchestration choices"},
                {"heading": "Quality evaluation",
                 "purpose": "Investigate user-visible failures",
                 "evidence_or_assumptions": "Observed failed job and offline checks",
                 "specific_analysis": "Describe recovery and acceptance criteria"}
            ],
            "presentation_strategy": "Use separate diagrams and one clear idea per slide",
            "report_strategy": "Write detailed sections and source limitations",
            "evidence_gaps": ["Unverified external timing measurements"]
        }
        cfg = SimpleNamespace(gemini_api_key="test",
                              gemini_model="gemini-test",request_timeout=40)
        with patch("rizzler.work_editorial.structured_decision",
                   new=__import__("unittest").mock.AsyncMock(return_value=draft)) as mock:
            result = await plan_editorial(
                "Create a detailed document and presentation",
                ["pdf", "pptx"], [], cfg=cfg)
        self.assertEqual(result["editorial_depth"], "comprehensive")
        self.assertIn("Architecture decisions",
                      as_instruction(validate(result), ["pdf", "pptx"]))
        self.assertEqual(mock.await_count, 1)
        bad = dict(result, sections=[result["sections"][0]] * 2)
        with self.assertRaises(CognitiveDecisionError):
            validate(bad)


class StoryboardAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_review_rejects_shallow_storyboard(self):
        from unittest.mock import AsyncMock
        from rizzler.work_ir import compile_ir
        from rizzler.work_presentation import compose_storyboard
        from rizzler.work_cognition import CognitiveDecisionError
        def slide(title, layout):
            return {"title": title, "layout": layout,
                    "headline": "Meaningful headline for stakeholders",
                    "points": ["Grounded specific mechanism and implications"],
                    "secondary": [], "metrics": [], "citations": [],
                    "notes": "Explain technical details and limitations",
                    "chart_x": "", "chart_y": ""}
        story = {"title": "Architecture briefing", "slides": [
            slide("Situation", "cover"), slide("Mechanisms", "bullets"),
            slide("Next actions", "closing")]}
        ir = compile_ir("Architecture briefing",
                        "# Current situation\nSubstantial technical analysis and concrete evidence.",
                        [])
        negative = {"passed": False,
                    "findings": [{"kind": "depth",
                                  "problem": "Missing concrete system alternatives and failure modes"}],
                    "summary": "The proposed briefing lacks requested engineering depth."}
        with patch.dict(os.environ, {"RIZZLER_V20_STORYBOARD_QA": "1"}), \
             patch("rizzler.work_presentation.structured_decision",
                   new=AsyncMock(return_value=story)) as plan, \
             patch("rizzler.work_cognition.review_semantics",
                   new=AsyncMock(return_value=negative)) as review:
            with self.assertRaises(CognitiveDecisionError):
                await compose_storyboard("Create an engineering architecture review", ir)
            self.assertEqual(plan.await_count, 3)
            self.assertEqual(review.await_count, 3)


class GatewayDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_timeout_has_independent_fallback(self):
        from rizzler.work_gemini_gateway import GeminiWorkGate
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "RIZZLER_WORK_ROOT": tmp,
            "RIZZLER_WORK_PROVIDER_RPM": "6",
            "RIZZLER_WORK_PROVIDER_TPM": "60000",
            "RIZZLER_WORK_PROVIDER_GAP_SECONDS": "0",
            "RIZZLER_WORK_PROVIDER_WAIT_SECONDS": "3"
        }):
            gate = GeminiWorkGate()
            attempted = []
            async def call(model):
                attempted.append(model)
                if model == "primary":
                    raise TimeoutError("local request deadline")
                return {"chosen": model}
            with patch("rizzler.production_guard.reserve_provider_call"):
                outcome = await gate.run(("primary", "independent_backup"),
                                         call, prompt_characters=90,
                                         max_output_tokens=250)
            self.assertEqual(outcome["chosen"], "independent_backup")
            self.assertEqual(attempted, ["primary", "independent_backup"])
            metrics = {m["model"]: m for m in gate.metrics()["model_outcomes"]}
            self.assertEqual(metrics["primary"]["transient_errors"], 1)


class TargetedRepairTests(unittest.TestCase):
    def test_one_section_repaired_without_dropping_other_sections(self):
        from rizzler.work_ir import compile_ir
        from rizzler.work_editorial import apply_section_repair
        from rizzler.work_cognition import CognitiveDecisionError
        ir = compile_ir(
            "Technical assessment",
            "## Baseline\nEvidence and validated assumptions are recorded here. "
            "The calculations remain source-bound.\n\n"
            "## Failure analysis\nAn initial failure mode is evaluated here. "
            "The diagnosis is incomplete.\n\n"
            "## Recommendations\nImplement bounded recovery and source-aware QA.",
            ["https://example.org/reference"])
        result = apply_section_repair(ir, {
            "title": ir.title,
            "edits": [{"section_index": 1,
                       "replacement_body": "The failure originated at the final "
                       "quality stage. Its precise nested exception remains "
                       "unverified; add durable substage telemetry and selective repair."}],
            "rationale": "Repair the incomplete failure diagnosis without modifying evidence."
        })
        self.assertEqual(result.sources, ir.sources)
        self.assertEqual(result.sections[0], ir.sections[0])
        self.assertEqual(result.sections[2], ir.sections[2])
        self.assertNotEqual(result.sections[1], ir.sections[1])
        self.assertNotEqual(result.sha256, ir.sha256)
        with self.assertRaises(CognitiveDecisionError):
            apply_section_repair(ir, {
                "title": ir.title, "edits": [{"section_index": 99,
                  "replacement_body": "An adequately detailed but invalid edit."}],
                "rationale": "This references a nonexistent section."})


if __name__ == "__main__":
    unittest.main()
