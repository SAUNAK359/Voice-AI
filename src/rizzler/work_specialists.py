"""Persistent specialist execution on top of the existing fenced WorkStore.

Each specialist is a bounded async stage with durable status, checkpoints, QA
verdicts, evidence lineage and retry-safe output reuse. External model calls
may repeat after crashes; committed artifacts are still fenced and verified.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import zipfile

from .artifacts import verify_artifact
from .contracts import FILE_FORMATS
from .work_agents import SPECS, gate_agent, plan, read_skill, result_receipts, verify_checkpoint
from .work_skills import render_one
from .work_sql import analyze_sql


def _valid_cached(spec, result: dict, checkpoint: Path, required: set[str]):
    gate_agent(spec.name, result, required)
    for receipt in result_receipts(result):
        candidate = checkpoint / receipt.name
        if not verify_checkpoint(candidate, receipt):
            raise ValueError("Persisted specialist artifact has failed checksum verification")
    return result


async def execute_specialists(store, claim: dict, worker_id: str, composer, researcher):
    jid, owner, fence = claim["id"], claim["owner"], claim["fence"]
    payload = claim["payload"]
    formats = set(payload["deliverables"])
    checkpoint = store.root / "checkpoints" / owner / jid
    checkpoint.mkdir(parents=True, exist_ok=True, mode=0o700)
    context = {"objective": payload["objective"], "sources": [], "text": None,
               "summary": None, "receipts": {}, "uploaded": []}

    async def run_agent(spec):
        saved = store.agent_checkpoint(jid, worker_id, fence, spec.name)
        if saved is not None:
            result = _valid_cached(spec, saved, checkpoint, formats)
        else:
            store.agent_begin(jid, worker_id, fence, spec.name, spec.sla_seconds)
            try:
                # Only curated, trusted specialist playbooks are loaded.
                read_skill(spec.name) if spec.name in (
                    "research", "sql_analytics", "powerpoint", "word",
                    "excel", "pdf_visual") else None
                result = await asyncio.wait_for(invoke(spec, checkpoint, context, formats,
                         payload, store, owner, composer, researcher),
                         timeout=spec.sla_seconds * 2)
                qa = gate_agent(spec.name, result, formats)
                for receipt in result_receipts(result):
                    if not verify_checkpoint(checkpoint / receipt.name, receipt):
                        raise ValueError("Specialist artifact disappeared before checkpoint commit")
                store.agent_complete(jid, worker_id, fence, spec.name, result, qa)
            except (asyncio.CancelledError, Exception):
                # Preserve the first error category without exposing private model output.
                try:
                    store.agent_error(jid, worker_id, fence, spec.name)
                except Exception:
                    pass
                raise
        if spec.name == "research":
            context["text"], context["sources"] = result["text"], result["sources"]
        elif spec.name == "sql_analytics":
            context["summary"] = result["summary"]
        elif spec.name == "orchestrator":
            context["text"] = result["text"]
        elif spec.name == "quality":
            context["quality"] = result
        else:
            for receipt in result_receipts(result):
                if receipt.kind in context["receipts"]:
                    raise ValueError("Duplicate output kind across specialists")
                context["receipts"][receipt.kind] = receipt
        return result

    for spec in plan(payload):
        await run_agent(spec)
        # Never allow a restored worker to retain the job without renewing
        # its parent lease between independently committed sub-agent stages.
        store.renew(jid, worker_id, fence, lease_seconds=45)

    text = context["text"] or "# Verified analysis\nNo ungrounded model conclusions were generated."
    if context["summary"]:
        text += "\n\n## Dataset quality (independently computed)\n" + json.dumps(
            context["summary"], ensure_ascii=False, indent=2)
    receipts = list(context["receipts"].values())
    store.finish(jid, worker_id, fence, text, receipts, checkpoint)


async def invoke(spec, checkpoint: Path, context: dict, formats: set[str],
                 payload: dict, store, owner, composer, researcher):
    name = spec.name
    if name == "research":
        text, sources = await researcher(payload["objective"])
        return {"text": text, "sources": sources}
    if name == "sql_analytics":
        uploads = payload.get("uploads", [])
        if len(uploads) != 1:
            raise ValueError("SQL analysis requires exactly one uploaded dataset")
        source = store.upload(owner, uploads[0])
        return await asyncio.to_thread(analyze_sql, source)
    if name == "orchestrator":
        text = await composer(payload["objective"], context["summary"])
        return {"text": text}
    if name == "quality":
        receipts = context["receipts"]
        expected = formats.intersection(FILE_FORMATS)
        missing = sorted(expected - receipts.keys())
        unexpected = sorted(receipts.keys() - expected)
        for receipt in receipts.values():
            if not verify_checkpoint(checkpoint / receipt.name, receipt):
                raise ValueError("Final quality gate failed artifact checksum")
            verified = verify_artifact(checkpoint / receipt.name, receipt.kind)
            if verified.sha256 != receipt.sha256 or not verified.verified:
                raise ValueError("Final quality gate failed structural receipt")
        if missing or unexpected:
            raise ValueError("Required deliverables missing or extra")
        if "research" in formats and not context["sources"]:
            raise ValueError("Research lineage missing grounding")
        if "data_analysis" in formats and not context["summary"]:
            raise ValueError("Analysis lineage missing independent SQL")
        if not context["text"] and not context["summary"]:
            raise ValueError("No substantive evidence to publish")
        return {"passed": True, "missing": missing, "artifacts": sorted(receipts),
                "evidence": {"grounded_urls": len(context["sources"]),
                             "sql_reconciled": bool(context["summary"])},
                "limits": "Structural and evidence QA, not a claim of presentation design superiority"}
    if name not in ("powerpoint", "word", "excel", "pdf_visual"):
        raise ValueError("Unknown specialist")
    requested = sorted(formats.intersection(spec.formats))
    receipts = []
    # One independent format-specific renderer, reusing the existing vetted
    # document generation tools rather than duplicating their implementations.
    for kind in [x for x in requested if x != "zip"]:
        table = None
        if payload.get("uploads"):
            from .work_skills import read_dataset
            table = await asyncio.to_thread(read_dataset,
                                             store.upload(owner, payload["uploads"][0]))
        path = checkpoint / (kind + "." + kind)
        working = checkpoint / (kind + "." + kind + ".partial")
        try:
            await asyncio.to_thread(render_one, kind, working, payload["objective"][:120],
                                    context["text"] or "# Dataset analysis\nVerified dataset statistics",
                                    table, context["sources"])
            verified = verify_artifact(working, kind)
            working.replace(path)
            receipts.append(verified)
        finally:
            working.unlink(missing_ok=True)
    if "zip" in requested:
        contents = list(context["receipts"].values()) + receipts
        if not contents:
            raise ValueError("ZIP requires a source output")
        path = checkpoint / "zip.zip"
        partial = checkpoint / "zip.zip.partial"
        try:
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for item in contents:
                    archive.write(checkpoint / item.name, arcname=item.name)
                archive.writestr("MANIFEST.json", json.dumps(
                    {"schema_version": 1, "files": [
                        {"name": r.name, "sha256": r.sha256, "bytes": r.byte_size}
                        for r in contents]}, indent=2))
            receipt = verify_artifact(partial, "zip")
            partial.replace(path)
            receipts.append(receipt)
        finally:
            partial.unlink(missing_ok=True)
    return {"receipts": [asdict(r) for r in receipts],
            "agent": name, "requested": requested}
