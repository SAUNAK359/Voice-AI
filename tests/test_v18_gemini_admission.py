"""Gemini V18: actual admission, model failover and graph contracts (no network)."""
import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rizzler.work_gemini_gateway import (
    GeminiWorkGate, WorkProviderUnavailable, model_sequence,
    provider_status,
)


class StatusError(Exception):
    def __init__(self, code):
        self.code=code


class WrappedError(Exception):
    pass


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ, {
            "RIZZLER_WORK_ROOT":self.tmp.name,
            "RIZZLER_WORK_PROVIDER_RPM":"6",
            "RIZZLER_WORK_PROVIDER_TPM":"24000",
            "RIZZLER_WORK_PROVIDER_PARALLEL":"1",
            "RIZZLER_WORK_PROVIDER_GAP_SECONDS":"0",
            "RIZZLER_WORK_PROVIDER_WAIT_SECONDS":"1",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_503_uses_authorized_fallback_once(self):
        gate=GeminiWorkGate()
        calls=[]
        async def ask(model):
            calls.append(model)
            if model=="primary":
                raise StatusError(503)
            return {"model":model}
        with patch("rizzler.production_guard.reserve_provider_call"):
            result=await gate.run(("primary","backup"),ask,
                                  prompt_characters=90,max_output_tokens=400)
        self.assertEqual(result,{"model":"backup"})
        self.assertEqual(calls,["primary","backup"])
        self.assertEqual(gate.metrics()["calls_last_60_seconds"],2)
        self.assertEqual(gate.metrics()["active"],0)

    async def test_429_does_not_fan_out_to_shared_quota(self):
        calls=[]
        async def ask(model):
            calls.append(model)
            raise StatusError(429)
        with patch("rizzler.production_guard.reserve_provider_call"):
            with self.assertRaises(WorkProviderUnavailable) as caught:
                await GeminiWorkGate().run(("primary","backup"),ask,
                    prompt_characters=10,max_output_tokens=150)
        self.assertEqual(caught.exception.status_code,429)
        self.assertEqual(calls,["primary"])

    async def test_rejected_permission_error_never_uses_fallback(self):
        calls=[]
        async def ask(model):
            calls.append(model)
            raise StatusError(401)
        with patch("rizzler.production_guard.reserve_provider_call"):
            with self.assertRaises(StatusError):
                await GeminiWorkGate().run(("primary","backup"),ask,
                    prompt_characters=10,max_output_tokens=150)
        self.assertEqual(calls,["primary"])

    async def test_shared_cross_instance_rate_admission(self):
        with patch.dict(os.environ,{"RIZZLER_WORK_PROVIDER_RPM":"1"}):
            first=GeminiWorkGate()
            second=GeminiWorkGate()
        uid=await first.acquire("alpha",100)
        first.release(uid)
        with self.assertRaises(WorkProviderUnavailable):
            await second.acquire("alpha",100)
        self.assertEqual(first.metrics()["calls_last_60_seconds"],1)

    async def test_circuit_is_model_specific(self):
        gate=GeminiWorkGate()
        gate.record("alpha",503)
        with self.assertRaises(WorkProviderUnavailable):
            await gate.acquire("alpha",250)
        uid=await gate.acquire("beta",250)
        gate.release(uid)

    def test_nested_503_unwrapped_without_text(self):
        root=WrappedError("potential sensitive material")
        root.__cause__=StatusError(503)
        self.assertEqual(provider_status(root),503)

    def test_model_ids_are_deduplicated_and_bounded(self):
        with patch.dict(os.environ,{"RIZZLER_WORK_FALLBACK_MODELS":"beta,alpha,beta"}):
            self.assertEqual(model_sequence("alpha"),("alpha","beta"))
        with patch.dict(os.environ,{"RIZZLER_WORK_FALLBACK_MODELS":"not valid"}):
            with self.assertRaises(ValueError):
                model_sequence("alpha")


class WorkPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_model_generated_valid_dag_no_deepagents_roundtrips(self):
        from rizzler.work_dynamic import generate,WorkModelConfig
        from rizzler.work_dynamic import validate
        import json
        data={"schema_version":2,"status":"ready","steps":[
            {"id":"orchestrator","tool":"orchestrator",
             "depends_on":[],"thinking_level":"medium"},
            {"id":"pdf_visual","tool":"pdf_visual",
             "depends_on":["orchestrator"],"thinking_level":"medium"},
            {"id":"quality","tool":"quality",
             "depends_on":["orchestrator","pdf_visual"],"thinking_level":"high"}]}
        payload={"objective":"Write a substantial markdown report",
                 "deliverables":["md"],"uploads":[],"evidence_scope":"auto"}
        class Response:
            text=json.dumps(data)
        async def fake(*a,**kw):
            return Response()
        with patch.dict(os.environ,{"RIZZLER_WORK_ORCHESTRATOR":"deepagents",
                                      "RIZZLER_WORK_LLM_BACKEND":"gemini"}), \
             patch("rizzler.work_gemini_gateway.gemini_content",new=fake), \
             patch("rizzler.work_deepagents.plan_with_deepagents",
                   side_effect=AssertionError("No recursive planner")):
            output=await generate(payload,WorkModelConfig("private","gemini-3.8-flash",45))
        self.assertEqual(output,data)
