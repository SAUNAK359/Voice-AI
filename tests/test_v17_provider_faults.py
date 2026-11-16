"""Bounded error handling for local and remote inference."""
import unittest
from rizzler.work_provider_retry import transient_code


class ProviderRecoveryTests(unittest.TestCase):
    def test_sglang_status_codes(self):
        SGLangProviderError=type("SGLangProviderError",(RuntimeError,),{})
        self.assertEqual(transient_code(SGLangProviderError("sglang_http_status_429")),
                         "provider_rate_limited")
        self.assertEqual(transient_code(SGLangProviderError("sglang_http_status_503")),
                         "provider_unavailable")
        self.assertIsNone(transient_code(SGLangProviderError("sglang_http_status_401")))
        self.assertIsNone(transient_code(SGLangProviderError("sglang_http_status_400")))
