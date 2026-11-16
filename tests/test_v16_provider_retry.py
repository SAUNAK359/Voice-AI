"""Provider deferral: stored next attempt, fenced lease and safe metadata."""
from __future__ import annotations
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from rizzler.work_store import WorkStore
from rizzler.work_provider_retry import transient_code, retry_delay


class RetryTests(unittest.TestCase):
    def test_rate_limit_retry_info_is_bounded(self):
        class ClientError(Exception):
            code=429
            response_json={"error":{"details":[{"retryDelay":"35s"}]}}
        err=ClientError("sensitive details must not appear in database")
        self.assertEqual(transient_code(err),"provider_rate_limited")
        self.assertEqual(retry_delay(err),35)

    def test_transient_worker_lease_is_persisted_and_fenced(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{
                "RIZZLER_AGENTIC_ENABLED":"1"}):
            store=WorkStore(root)
            job=store.submit("owner_001", "Prepare the sales briefing",
                             ["md"], "retry_key_0001", [])
            claimed=store.claim("worker_alpha",lease_seconds=45)
            self.assertEqual(claimed["id"],job["id"])
            store.defer(claimed["id"], "worker_alpha", claimed["fence"],
                        "provider_rate_limited", delay_seconds=35)
            self.assertEqual(store.get("owner_001",job["id"])["status"],"queued")
            self.assertIsNone(store.claim("worker_beta",lease_seconds=45))
            with patch("rizzler.work_store.time.time",return_value=time.time()+40):
                retry=store.claim("worker_beta",lease_seconds=45)
            self.assertEqual(retry["id"],job["id"])
            self.assertGreater(retry["fence"],claimed["fence"])
            self.assertEqual(len(store.list_jobs("owner_001")),1)

    def test_invalid_provider_error_is_not_marked_retryable(self):
        class AuthenticationError(Exception):
            code=401
        self.assertIsNone(transient_code(AuthenticationError()))
