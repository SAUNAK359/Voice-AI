"""V22 Deep Agents delegated synthesis contracts and provider recovery."""
from __future__ import annotations

import importlib.util
import json
import unittest
from types import SimpleNamespace

from rizzler.work_deepagents_synthesis import validate_draft, DeepSynthesisError
from rizzler.work_provider_retry import transient_code


class DraftContractTests(unittest.TestCase):
    def test_rejects_empty_outlines_and_slide_instructions(self):
        for text in ("", "# Executive briefing\nShort.",
                     "# A\n\n## B\n\nSLIDE 4: Draft planning text " + "x"*130):
            with self.subTest(text=text[:20]),self.assertRaises(DeepSynthesisError):
                validate_draft(text)

    def test_accepts_complete_report_and_preserves_original_sections(self):
        body = ("# Technical findings\n\n"
                "## Current architecture\n\n"
                "The workflow persists every source and intermediate result; "
                "verified claims require traceable evidence and reproducible "
                "calculations.\n\n"
                "## Failure recovery\n\n"
                "The provider's transient errors must be handled using "
                "durable checkpoints rather than recreating all outputs.\n\n"
                "## Limitations\n\n"
                "The reported data was not independently inspected.")
        self.assertEqual(validate_draft(body),body)

    def test_synthesis_failure_reports_actionable_diagnosis(self):
        from rizzler.work_cognition import failure_code
        from rizzler.work_decision_plane import diagnosis
        error = DeepSynthesisError("no_valid_draft: not_submitted")
        self.assertEqual(failure_code(error), "deep_synthesis_failed")
        self.assertEqual(diagnosis(error), "deep_synthesis_no_draft")

    def test_synthesis_provider_error_is_deferred(self):
        self.assertEqual(transient_code(DeepSynthesisError("provider_unavailable")),
                         "provider_unavailable")
        self.assertEqual(transient_code(DeepSynthesisError("provider_rate_limited")),
                         "provider_rate_limited")


@unittest.skipUnless(
    importlib.util.find_spec("deepagents") is not None and
    importlib.util.find_spec("langchain_core") is not None,
    "Deep Agents dependencies optional for no-deps CI")
class DelegationContracts(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_delegation_cannot_publish_without_valid_tool_submission(self):
        from rizzler.work_deepagents_synthesis import synthesize_with_deepagents
        manuscript=(
            "# Findings\n\n## Root cause\n\n"
            + "A model reviewer cannot safely publish without evidence. "*5
            + "\n\n## Recommendations\n\n"
            + "Persist model-selected research, verify claims and render "
              "professional artifact layouts separately.")
        captured=[]
        def factory(*,model,tools,system_prompt,subagents):
            self.assertEqual(len(tools),4)
            self.assertEqual(subagents[0]["name"],"editorial_reviewer")
            self.assertEqual(len(subagents[0]["tools"]),3)
            class Fake:
                async def ainvoke(self,values,config):
                    evidence=tools[0].invoke({})
                    captured.append(json.loads(evidence))
                    accepted=tools[1].invoke({"markdown":manuscript})
                    captured.append(accepted)
                    return {"messages":[]}
            return Fake()
        got=await synthesize_with_deepagents(
            "Build a source-grounded technical report",
            "# Source findings\nThis evidence is provider-attributed only.",
            ["https://example.com/research"],None,
            SimpleNamespace(request_timeout=40),model=object(),factory=factory)
        self.assertEqual(got,manuscript)
        self.assertEqual(captured[0]["source_urls"],["https://example.com/research"])
        self.assertEqual(captured[1],"accepted_for_independent_quality_review")

    async def test_missing_submission_must_fail_closed(self):
        from rizzler.work_deepagents_synthesis import synthesize_with_deepagents
        def factory(**kwargs):
            class Fake:
                async def ainvoke(self,values,config):
                    return {"messages":[]}
            return Fake()
        with self.assertRaisesRegex(DeepSynthesisError,"no_valid_draft"):
            await synthesize_with_deepagents(
                "Write a researched report","",[],None,
                SimpleNamespace(request_timeout=40),
                model=object(),factory=factory)


@unittest.skipUnless(
    importlib.util.find_spec("langchain_google_genai") is not None and
    importlib.util.find_spec("langchain_core") is not None,
    "Gemini LangChain adapter optional in dependency-free core CI")
class FullDurationAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_recursive_generation_lease_held_until_model_finishes(self):
        import asyncio
        import os
        import tempfile
        from unittest.mock import patch
        from langchain_core.messages import HumanMessage
        from langchain_google_genai import ChatGoogleGenerativeAI
        from rizzler.work_deepagents_model import create_gated_model
        from rizzler.work_gemini_gateway import GeminiWorkGate

        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "RIZZLER_WORK_ROOT":root,
            "RIZZLER_WORK_PROVIDER_PARALLEL":"3",
            "RIZZLER_WORK_PROVIDER_RPM":"100",
            "RIZZLER_WORK_PROVIDER_TPM":"100000",
            "RIZZLER_WORK_PROVIDER_GAP_SECONDS":"0",
            "RIZZLER_WORK_PROVIDER_WAIT_SECONDS":"3"}):
            cfg=SimpleNamespace(gemini_model="gemini-test",
                                gemini_api_key="test-only-not-a-real-api-key",
                                request_timeout=20)
            model=create_gated_model(cfg)
            started=asyncio.Event()
            resume=asyncio.Event()
            async def fake_generation(_self,*args,**kwargs):
                started.set()
                await resume.wait()
                return {"synthetic":"accepted"}
            with patch.object(ChatGoogleGenerativeAI,"_agenerate",
                              new=fake_generation), \
                 patch("rizzler.production_guard.reserve_provider_call"):
                task=asyncio.create_task(model._agenerate([
                    HumanMessage(content="Write one test answer")]))
                try:
                    await asyncio.wait_for(started.wait(),4)
                    self.assertEqual(GeminiWorkGate().metrics()["active"],1)
                finally:
                    resume.set()
                self.assertEqual(await asyncio.wait_for(task,4),
                                 {"synthetic":"accepted"})
                self.assertEqual(GeminiWorkGate().metrics()["active"],0)


if __name__=="__main__":
    unittest.main()
