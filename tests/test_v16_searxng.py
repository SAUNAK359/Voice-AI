"""Search gateway offline security contracts; no outside calls."""
import os
import unittest
from unittest.mock import patch
from rizzler.work_searxng import (
    configuration, selected, search_ready, SearchUnavailable)


class SearchContracts(unittest.TestCase):
    def test_keyless_local_endpoint_config(self):
        with patch.dict(os.environ,{
            "RIZZLER_SEARCH_BACKEND":"searxng",
            "RIZZLER_WORK_LLM_BACKEND":"sglang",
            "RIZZLER_SEARXNG_URL":"http://127.0.0.1:8081"}):
            self.assertTrue(selected())
            self.assertTrue(search_ready())

    def test_untrusted_remote_http_is_rejected(self):
        with patch.dict(os.environ,{
            "RIZZLER_SEARXNG_URL":"http://example.com:8080",
            "RIZZLER_SEARXNG_TRUSTED_HOSTS":""}):
            with self.assertRaises(SearchUnavailable):
                configuration()

    def test_credentialed_service_url_rejected(self):
        with patch.dict(os.environ,{"RIZZLER_SEARXNG_URL":"http://user:pass@localhost:8081"}):
            with self.assertRaises(SearchUnavailable):
                configuration()

    def test_backend_must_be_selected(self):
        with patch.dict(os.environ,{"RIZZLER_SEARCH_BACKEND":"gemini",
                                     "RIZZLER_WORK_LLM_BACKEND":"sglang"}):
            self.assertFalse(search_ready())
