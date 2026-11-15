"""V15 asynchronous waiting: do not cancel slow model work arbitrarily.

Provider errors, cancellation and durable fencing remain intentional boundaries.
"""
import asyncio
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from rizzler.work_async import async_wait_enabled, stage_timeout, wait_scope


class WorkAsyncConfigurationTests(TestCase):
    def test_enabled_by_default_and_no_stage_deadline(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(async_wait_enabled())
            self.assertIsNone(stage_timeout(0.01))

    def test_disabled_restores_configured_deadlines(self):
        with patch.dict("os.environ", {"RIZZLER_WORK_ASYNC_WAIT": "off"}):
            self.assertFalse(async_wait_enabled())
            self.assertEqual(stage_timeout(0.02), 0.02)

    def test_bad_configuration_fails_closed(self):
        with patch.dict("os.environ", {"RIZZLER_WORK_ASYNC_WAIT": "foreverish"}):
            with self.assertRaises(ValueError):
                async_wait_enabled()


class WorkAsyncWaitingTests(IsolatedAsyncioTestCase):
    async def test_long_job_is_awaited_not_cancelled(self):
        with patch.dict("os.environ", {"RIZZLER_WORK_ASYNC_WAIT": "on"}):
            async with wait_scope(0.001):
                await asyncio.sleep(0.025)
            result=await asyncio.wait_for(asyncio.sleep(0.005,result="completed"),0.5)
            self.assertEqual(result,"completed")

    async def test_explicit_cancel_is_not_suppressed(self):
        async def slow():
            async with wait_scope(0.001):
                await asyncio.sleep(10)
        with patch.dict("os.environ", {"RIZZLER_WORK_ASYNC_WAIT": "on"}):
            task=asyncio.create_task(slow())
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_provider_failure_is_not_hidden(self):
        with patch.dict("os.environ", {"RIZZLER_WORK_ASYNC_WAIT": "on"}):
            with self.assertRaises(ConnectionError):
                async with wait_scope(0.001):
                    await asyncio.sleep(0)
                    raise ConnectionError("Remote provider unavailable")

    async def test_off_mode_enforces_original_limit(self):
        with patch.dict("os.environ", {"RIZZLER_WORK_ASYNC_WAIT": "off"}):
            with self.assertRaises(TimeoutError):
                async with wait_scope(0.005):
                    await asyncio.sleep(0.03)
