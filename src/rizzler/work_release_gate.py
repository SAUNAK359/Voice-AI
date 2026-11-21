"""V26 final release proof gate: no self-certified production claims.

Each of the 18 specification gates needs a real, content-hashed evidence
receipt. A model, unit test, or generated YAML cannot grant external
human/operations signoff. Missing evidence is NOT_RUN, not automatically PASS.
"""
from __future__ import annotations

from datetime import datetime,timezone
import hashlib
import hmac
import json
from pathlib import Path
import re

GATES={f"G{i:02d}":label for i,label in enumerate((
    "source_integrity","build_compatibility","unit_schema",
    "data_integrity","source_provenance","context_correctness",
    "professional_content","native_artifacts","semantic_visuals",
    "cross_artifact_consistency","safe_recovery","durability",
    "provider_reliability","security","load_cost",
    "multi_domain_generalization","human_blind_review",
    "staging_deployment_rollback"))}
STATUSES=frozenset({"PASS","FAIL","NOT_RUN"})
SHA=re.compile(r"^[a-f0-9]{40}$")
DIGEST=re.compile(r"^[a-f0-9]{64}$")
MAX_PROOF_BYTES=12_000_000
EXTERNAL_SIGNOFF="EXTERNAL_RELEASE_SIGNOFF.json"


class ReleaseEvidenceError(ValueError):
    """One release receipt is malformed, stale or untrustworthy."""


def _read_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size>40_000:
        raise ReleaseEvidenceError("Release record missing or oversized")
    try:
        result=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc:
        raise ReleaseEvidenceError("Invalid release JSON") from exc
    if not isinstance(result,dict):
        raise ReleaseEvidenceError("Release JSON must be an object")
    return result


def _canonical(data: dict) -> bytes:
    return json.dumps(data,sort_keys=True,separators=(",",":"),
                      ensure_ascii=False,allow_nan=False).encode("utf-8")


def _digest_file(path: Path) -> str:
    hasher=hashlib.sha256()
    with path.open("rb") as source:
        for buffer in iter(lambda:source.read(1024*1024),b""):
            hasher.update(buffer)
    return hasher.hexdigest()


def read_gate_receipt(evidence_root: Path,gate_id: str,
                      *,source_sha: str) -> dict:
    if gate_id not in GATES or not SHA.fullmatch(source_sha):
        raise ReleaseEvidenceError("Unrecognized release source or gate")
    root=Path(evidence_root).resolve()
    path=root/"gates"/(gate_id+".json")
    if not path.exists():
        return {"gate":gate_id,"status":"NOT_RUN",
                "category":"missing_evidence_record"}
    receipt=_read_json(path)
    if set(receipt)!={"schema_version","gate","status","source_sha",
                     "proof_path","proof_sha256","run_id","executed_utc",
                     "evaluator","limitations"}:
        raise ReleaseEvidenceError("Unexpected release receipt schema")
    if (receipt["schema_version"]!=1 or receipt["gate"]!=gate_id
            or receipt["status"] not in STATUSES
            or receipt["source_sha"]!=source_sha):
        raise ReleaseEvidenceError("Gate receipt disagrees with exact source")
    for key,minimum,maximum in (
            ("run_id",8,128),("evaluator",4,120),
            ("limitations",0,1000),("executed_utc",16,45)):
        value=receipt[key]
        if not isinstance(value,str) or not minimum<=len(value)<=maximum:
            raise ReleaseEvidenceError("Invalid release metadata")
    try:
        moment=datetime.fromisoformat(receipt["executed_utc"].replace("Z","+00:00"))
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("Naive timestamp")
        if moment.astimezone(timezone.utc)>datetime.now(timezone.utc):
            raise ValueError("Future release measurement")
    except (ValueError,TypeError) as exc:
        raise ReleaseEvidenceError("Invalid UTC execution timestamp") from exc
    if receipt["status"]=="NOT_RUN":
        if receipt["proof_path"] not in (None,"") or receipt["proof_sha256"] not in (None,""):
            raise ReleaseEvidenceError("Unrun release gate includes synthetic proof")
        return {"gate":gate_id,"status":"NOT_RUN","category":"explicit_not_run"}
    location=receipt["proof_path"]
    if (not isinstance(location,str) or not location.startswith("proofs/")
            or "\\" in location or any(part in (".","..","")
                for part in location.split("/"))):
        raise ReleaseEvidenceError("Unsafe or external proof path")
    target=(root/location).resolve()
    if root not in target.parents or not target.is_file() or target.is_symlink():
        raise ReleaseEvidenceError("Release proof does not exist in allowed directory")
    if not 16<=target.stat().st_size<=MAX_PROOF_BYTES:
        raise ReleaseEvidenceError("Release proof empty or oversized")
    actual=_digest_file(target)
    if (not isinstance(receipt["proof_sha256"],str)
            or not DIGEST.fullmatch(receipt["proof_sha256"])
            or actual!=receipt["proof_sha256"]):
        raise ReleaseEvidenceError("Release proof hash mismatch")
    return {"gate":gate_id,"status":receipt["status"],
            "proof_sha256":actual,"run_id":receipt["run_id"],
            "evaluator":receipt["evaluator"]}


def _verify_external_signoff(root: Path,source_sha: str,
                             *,verification_key: bytes | None,
                             supported_scope: list[str]) -> bool:
    """Separate operator release approval, not an agent's own gate score."""
    if verification_key is None or len(verification_key)<32:
        return False
    path=root/EXTERNAL_SIGNOFF
    if not path.is_file():
        return False
    try:
        record=_read_json(path)
        if set(record)!={"schema_version","source_sha","supported_scope",
                         "independent_reviewers","staging_verified",
                         "rollback_verified","monitoring_verified",
                         "approved_utc","hmac_sha256"}:
            return False
        if (record["schema_version"]!=1 or record["source_sha"]!=source_sha
                or record["supported_scope"]!=supported_scope
                or not record["staging_verified"]
                or not record["rollback_verified"]
                or not record["monitoring_verified"]
                or not isinstance(record["independent_reviewers"],list)
                or len(set(record["independent_reviewers"]))<2):
            return False
        if any(not isinstance(r,str) or not 4<=len(r)<=120
               for r in record["independent_reviewers"]):
            return False
        approved=datetime.fromisoformat(
            record["approved_utc"].replace("Z","+00:00"))
        if approved.tzinfo is None or approved>datetime.now(timezone.utc):
            return False
        evidence={k:v for k,v in record.items() if k!="hmac_sha256"}
        expected=hmac.new(verification_key,_canonical(evidence),
                          hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected,record["hmac_sha256"])
    except (ValueError,TypeError,OSError,KeyError):
        return False


def evaluate_release(evidence_root: Path,*,source_sha: str,
                     supported_scope: list[str],
                     operator_verification_key: bytes | None = None) -> dict:
    """Fail closed on a single critical failure or unaudited release gate."""
    if (not SHA.fullmatch(source_sha)
            or not isinstance(supported_scope,list)
            or not 1<=len(supported_scope)<=30
            or any(not isinstance(s,str) or not 3<=len(s)<=150
                   for s in supported_scope)):
        raise ReleaseEvidenceError("Missing source SHA or declared release scope")
    root=Path(evidence_root).resolve()
    if not root.is_dir():
        raise ReleaseEvidenceError("Missing release evidence directory")
    observed=[]
    for gate in GATES:
        try:
            observed.append(read_gate_receipt(root,gate,source_sha=source_sha))
        except ReleaseEvidenceError:
            observed.append({"gate":gate,"status":"FAIL",
                             "category":"receipt_integrity_failed"})
    states={x["gate"]:x["status"] for x in observed}
    blocked=[key for key,value in states.items() if value=="FAIL"]
    pending=[key for key,value in states.items() if value=="NOT_RUN"]
    first_four=all(states[f"G{i:02d}"]=="PASS" for i in range(4))
    staging=all(states[f"G{i:02d}"]=="PASS" for i in range(15))
    all_passed=not blocked and not pending
    signoff=_verify_external_signoff(
        root,source_sha,verification_key=operator_verification_key,
        supported_scope=supported_scope) if staging and not blocked else False
    if blocked or not first_four:
        status="NOT_READY"
    elif all_passed and signoff:
        status="PRODUCTION_QUALIFIED_FOR_DECLARED_SCOPE"
    elif staging and signoff:
        status="STAGING_QUALIFIED"
    elif staging and not blocked:
        status="CANDIDATE"
    else:
        status="CANDIDATE"
    return {
        "schema_version":1,"source_sha":source_sha,
        "supported_scope":supported_scope,"status":status,
        "gates":observed,"failed":blocked,"not_run":pending,
        "external_operations_signoff_verified":signoff,
        "limitations":"Content hashes verify supplied proof bytes, not "
          "the independent authenticity of every underlying measurement. "
          "Human/staging/operations signoff remains separately required.",
    }
