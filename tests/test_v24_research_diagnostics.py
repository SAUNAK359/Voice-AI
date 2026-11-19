"""Research failure triage must preserve safety and actionable categories."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rizzler.work_research_errors import (
    ResearchQualificationError, failure_categories)
from rizzler.work_diagnostics import failure_code, failure_record


class ResearchFailureDiagnosticTests(unittest.TestCase):
    def test_no_grounded_sources_is_not_a_generic_artifact_error(self):
        try:
            raise ResearchQualificationError(
                "no_grounded_search_response",
                counts={"empty_grounding_metadata": 2,
                        "research_provider_error": 1})
        except ResearchQualificationError as exc:
            self.assertEqual(
                failure_code(exc), "research_no_grounded_search_response")
            record=failure_record(exc, "research")
        self.assertEqual(record["research_reason"],
                         "no_grounded_search_response")
        self.assertEqual(
            record["research_failure_categories"]["empty_grounding_metadata"],2)
        self.assertIn("fingerprint", record)
        self.assertNotIn("provider_message",record)

    def test_verified_quote_failure_has_explicit_gate_code(self):
        error=ResearchQualificationError("missing_verified_quotes")
        self.assertEqual(
            failure_code(error),"research_missing_verified_quotes")

    def test_diagnostics_cannot_include_unapproved_labels(self):
        with self.assertRaises(ValueError):
            ResearchQualificationError(
                "missing_verified_quotes",
                counts={"https://secret.example?token=private":1})
        with self.assertRaises(ValueError):
            ResearchQualificationError("unexpected_user_facts")

    def test_safe_research_categories_survive_persistent_store_contract(self):
        import tempfile
        from rizzler.work_store import WorkStore
        with tempfile.TemporaryDirectory() as root:
            store = WorkStore(root)
            job = store.submit("owner", "Create a diagnostic document",
                               ["txt"], "research-diagnostic-001", [])
            try:
                raise ResearchQualificationError(
                    "missing_verified_quotes",
                    counts={"empty_grounding_metadata": 2})
            except ResearchQualificationError as exc:
                record = failure_record(exc, "research")
            with store._tx() as cursor:
                store._diagnostic(cursor, job["id"], "owner", record)
            found = store.diagnostics("owner", job["id"])
            self.assertEqual(len(found), 1)
            self.assertEqual(
                found[0]["research_reason"], "missing_verified_quotes")
            record["research_failure_categories"] = {
                "https://private.example?key=secret": 1}
            with self.assertRaises(ValueError):
                with store._tx() as cursor:
                    store._diagnostic(cursor, job["id"], "owner", record)

    def test_distinct_research_call_errors_are_safely_aggregated(self):
        errors=[
            ResearchQualificationError("empty_grounding_metadata"),
            ResearchQualificationError("short_search_answer"),
            ValueError("SENSITIVE MODEL TEXT"),
            RuntimeError("token=SECRET"),
        ]
        counts=failure_categories(errors)
        self.assertEqual(counts,{
            "empty_grounding_metadata":1,
            "invalid_provider_contract":1,
            "research_provider_error":1,
            "short_search_answer":1})
        self.assertNotIn("SECRET",str(counts))
        self.assertNotIn("SENSITIVE",str(counts))


if __name__=="__main__":
    unittest.main()
