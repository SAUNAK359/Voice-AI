"""V26 final release accepts actual evidence, never plausible text-only status."""
from __future__ import annotations

from datetime import datetime,timezone
import hashlib
import hmac
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rizzler.work_release_gate import (
    evaluate_release,read_gate_receipt,GATES,
    ReleaseEvidenceError,_canonical)


SOURCE="c"*40
SCOPE=["research-backed-office-artifacts"]
SIGNING_KEY=b"local-unit-test-only-operator-signing-material-123456"

def make_receipt(root: Path, gate: str, status="PASS", source=SOURCE):
    (root/"gates").mkdir(parents=True,exist_ok=True)
    (root/"proofs").mkdir(parents=True,exist_ok=True)
    proof="proofs/"+gate+".json"
    payload=("real test execution fixture for "+gate).encode()
    (root/proof).write_bytes(payload)
    record={
        "schema_version":1,"gate":gate,"status":status,
        "source_sha":source,"proof_path":proof,
        "proof_sha256":hashlib.sha256(payload).hexdigest(),
        "run_id":"actual-test-run-id-1001",
        "executed_utc":datetime.now(timezone.utc).isoformat(),
        "evaluator":"test runner",
        "limitations":"This isolated test proves schema behavior, not real release acceptance."
    }
    (root/"gates"/(gate+".json")).write_text(
        json.dumps(record),encoding="utf-8")
    return record


def add_independent_operator_attestation(root: Path):
    record={
        "schema_version":1,"source_sha":SOURCE,
        "supported_scope":SCOPE,
        "independent_reviewers":["reviewer_A","reviewer_B"],
        "staging_verified":True,
        "rollback_verified":True,
        "monitoring_verified":True,
        "approved_utc":datetime.now(timezone.utc).isoformat(),
    }
    record["hmac_sha256"]=hmac.new(
        SIGNING_KEY,_canonical(record),hashlib.sha256).hexdigest()
    (root/"EXTERNAL_RELEASE_SIGNOFF.json").write_text(
        json.dumps(record),encoding="utf-8")


class V26ReleaseEvidenceTests(unittest.TestCase):
    def test_all_unrun_is_not_ready(self):
        with TemporaryDirectory() as temp:
            result=evaluate_release(
                Path(temp),source_sha=SOURCE,supported_scope=SCOPE)
            self.assertEqual(result["status"],"NOT_READY")
            self.assertEqual(len(result["not_run"]),18)
            self.assertFalse(result["external_operations_signoff_verified"])

    def test_missing_evidence_or_hash_mismatch_fail_closed(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            record=make_receipt(root,"G00")
            self.assertEqual(read_gate_receipt(
                root,"G00",source_sha=SOURCE)["status"],"PASS")
            (root/record["proof_path"]).write_text("tampered")
            with self.assertRaises(ReleaseEvidenceError):
                read_gate_receipt(root,"G00",source_sha=SOURCE)
            status=evaluate_release(root,source_sha=SOURCE,
                                    supported_scope=SCOPE)
            self.assertIn("G00",status["failed"])
            self.assertEqual(status["status"],"NOT_READY")

    def test_source_commit_mismatch_is_not_a_valid_release_receipt(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            make_receipt(root,"G00",source="d"*40)
            with self.assertRaises(ReleaseEvidenceError):
                read_gate_receipt(root,"G00",source_sha=SOURCE)

    def test_reject_path_traversal_in_release_proof(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            record=make_receipt(root,"G00")
            record["proof_path"]="proofs/../../stolen.txt"
            (root/"gates"/"G00.json").write_text(json.dumps(record))
            with self.assertRaises(ReleaseEvidenceError):
                read_gate_receipt(root,"G00",source_sha=SOURCE)

    def test_partial_technical_pass_is_not_production(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            for i in range(4):
                make_receipt(root,f"G{i:02d}")
            result=evaluate_release(root,source_sha=SOURCE,
                                    supported_scope=SCOPE)
            self.assertEqual(result["status"],"CANDIDATE")
            self.assertIn("G16",result["not_run"])

    def test_even_all_hashed_gate_proofs_without_signoff_not_production(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            for name in GATES:
                make_receipt(root,name)
            result=evaluate_release(root,source_sha=SOURCE,
                                    supported_scope=SCOPE)
            self.assertEqual(result["status"],"CANDIDATE")
            self.assertFalse(result["external_operations_signoff_verified"])

    def test_operator_signoff_binds_exact_source_and_supported_scope(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            for name in GATES:
                make_receipt(root,name)
            add_independent_operator_attestation(root)
            result=evaluate_release(
                root,source_sha=SOURCE,supported_scope=SCOPE,
                operator_verification_key=SIGNING_KEY)
            self.assertEqual(result["status"],
                             "PRODUCTION_QUALIFIED_FOR_DECLARED_SCOPE")
            self.assertTrue(result["external_operations_signoff_verified"])
            wrong=evaluate_release(
                root,source_sha=SOURCE,supported_scope=SCOPE,
                operator_verification_key=b"x"*32)
            self.assertNotEqual(wrong["status"],
                                "PRODUCTION_QUALIFIED_FOR_DECLARED_SCOPE")

    def test_known_failure_blocks_even_valid_operator_signoff(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            for name in GATES:
                make_receipt(root,name)
            add_independent_operator_attestation(root)
            make_receipt(root,"G03",status="FAIL")
            result=evaluate_release(
                root,source_sha=SOURCE,supported_scope=SCOPE,
                operator_verification_key=SIGNING_KEY)
            self.assertEqual(result["status"],"NOT_READY")
            self.assertIn("G03",result["failed"])


if __name__=="__main__":
    unittest.main()
