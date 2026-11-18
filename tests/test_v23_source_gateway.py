"""V23 outbound-evidence policy tests. No external hosts are contacted."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rizzler.source_gateway import canonical_evidence_url, require_public_ip, fetch_source


class EvidenceGatewayPolicyTests(unittest.TestCase):
    def test_only_global_addresses_can_be_used(self):
        for value in ("127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1",
                      "169.254.169.254", "::1", "fc00::1", "fe80::1", "0.0.0.0"):
            with self.subTest(value=value), self.assertRaises(PermissionError):
                require_public_ip(value)
        self.assertEqual(require_public_ip("8.8.8.8"), "8.8.8.8")
        self.assertEqual(require_public_ip("2606:4700:4700::1111"),
                         "2606:4700:4700::1111")

    def test_refuses_unsafe_destination_schemes_credentials_ports(self):
        invalid = ("http://example.org/", "file:///etc/passwd",
                   "https://127.0.0.1/", "https://localhost/",
                   "https://metadata.google.internal/",
                   "https://example.org:8443/data", "https://user:pw@example.org/")
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(PermissionError):
                canonical_evidence_url(url)
        self.assertEqual(canonical_evidence_url("https://example.org/report"),
                         "https://example.org/report")

    def test_budget_parameters_rejected_before_network_calls(self):
        import asyncio
        with self.assertRaises(ValueError):
            asyncio.run(fetch_source("https://example.org/", source_id="example",
                                     max_bytes=999))
        with self.assertRaises(ValueError):
            asyncio.run(fetch_source("https://example.org/", source_id="example",
                                     timeout=0.01))


if __name__ == "__main__":
    unittest.main()
