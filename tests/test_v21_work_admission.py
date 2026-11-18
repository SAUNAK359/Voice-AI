"""V21: three-slot Work model concurrency, health control and defer semantics."""
import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from rizzler.work_gemini_gateway import (
    GeminiWorkGate, WorkLocalAdmissionBusy,
)
from rizzler.work_cognition import failure_code
from rizzler.work_provider_retry import transient_code


class ThreeSlotAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,{
            "RIZZLER_WORK_ROOT":tmp.name,
            "RIZZLER_WORK_PROVIDER_PARALLEL":"3",
            "RIZZLER_WORK_PROVIDER_ADAPTIVE":"1",
            "RIZZLER_WORK_PROVIDER_RPM":"100",
            "RIZZLER_WORK_PROVIDER_TPM":"100000",
            "RIZZLER_WORK_PROVIDER_GAP_SECONDS":"0",
            "RIZZLER_WORK_PROVIDER_WAIT_SECONDS":"1",
            "RIZZLER_WORK_PROVIDER_RECOVERY_SUCCESSES":"2",
            "RIZZLER_WORK_PROVIDER_RECOVERY_SECONDS":"5",
        })
        env.start()
        self.addCleanup(env.stop)

    async def test_three_across_instances_and_fourth_waits(self):
        first=GeminiWorkGate()
        other=GeminiWorkGate()
        slots=await asyncio.gather(*(first.acquire("alpha",500)
                                     for _ in range(3)))
        self.assertEqual(len(set(slots)),3)
        self.assertEqual(other.metrics()["active"],3)
        self.assertEqual(other.metrics()["effective_parallel_limit"],3)
        fourth=asyncio.create_task(other.acquire("alpha",500))
        try:
            await asyncio.sleep(0.08)
            self.assertFalse(fourth.done())
            first.release(slots[0])
            uid=await asyncio.wait_for(fourth,1)
            self.assertTrue(uid)
            self.assertEqual(first.metrics()["active"],3)
            other.release(uid)
        finally:
            if not fourth.done():
                fourth.cancel()
                await asyncio.gather(fourth,return_exceptions=True)
            for uid in slots[1:]:
                first.release(uid)
        self.assertEqual(first.metrics()["active"],0)

    async def test_health_reduces_capacity_and_recovers_gradually(self):
        gate=GeminiWorkGate()
        self.assertEqual(gate.metrics()["effective_parallel_limit"],3)
        gate.record("failing_model",503)
        self.assertEqual(gate.metrics()["effective_parallel_limit"],2)
        # A healthy fallback can still execute, but only two may be leased.
        slots=await asyncio.gather(*(gate.acquire("healthy_model",500)
                                     for _ in range(2)))
        self.assertEqual(gate.metrics()["active"],2)
        for uid in slots:gate.release(uid)
        gate.record("failing_model",503)
        self.assertEqual(gate.metrics()["effective_parallel_limit"],1)
        # Simulated passage of recovery window; no API call or actual delay.
        current=time.time()
        with patch("rizzler.work_gemini_gateway.time.time",
                   return_value=current+8):
            gate.record("healthy_model",None)
            gate.record("healthy_model",None)
            self.assertEqual(gate.metrics()["effective_parallel_limit"],2)
        with patch("rizzler.work_gemini_gateway.time.time",
                   return_value=current+16):
            gate.record("healthy_model",None)
            gate.record("healthy_model",None)
            self.assertEqual(gate.metrics()["effective_parallel_limit"],3)

    async def test_provider_429_reduces_to_one(self):
        gate=GeminiWorkGate()
        gate.record("alpha",429)
        metrics=gate.metrics()
        self.assertEqual(metrics["effective_parallel_limit"],1)
        self.assertGreater(metrics["model_circuits_open"],0)

    async def test_local_saturation_is_not_google_429(self):
        with patch.dict(os.environ,{
            "RIZZLER_WORK_PROVIDER_PARALLEL":"1",
            "RIZZLER_WORK_PROVIDER_WAIT_SECONDS":"1"}):
            gate=GeminiWorkGate()
            slot=await gate.acquire("alpha",500)
            try:
                with self.assertRaises(WorkLocalAdmissionBusy) as caught:
                    await gate.acquire("beta",500)
                self.assertEqual(failure_code(caught.exception),
                                 "local_admission_busy")
                self.assertEqual(transient_code(caught.exception),
                                 "local_admission_busy")
                self.assertEqual(gate.metrics()["model_circuits_open"],0)
            finally:
                gate.release(slot)

    async def test_non_provider_error_not_counted_as_success(self):
        gate=GeminiWorkGate()
        async def bad(_model):
            raise RuntimeError("unexpected internal decoder issue")
        with patch("rizzler.production_guard.reserve_provider_call"):
            with self.assertRaises(RuntimeError):
                await gate.run(("alpha",),bad,prompt_characters=30,
                               max_output_tokens=100)
        metrics=gate.metrics()
        outcome=next(x for x in metrics["model_outcomes"]
                     if x["model"]=="alpha")
        self.assertEqual(outcome["successes"],0)
        self.assertEqual(outcome["rejected"],1)


if __name__=="__main__":
    unittest.main()
