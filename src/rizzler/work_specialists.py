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
from .work_ir import compile_ir
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
               "summary": None, "receipts": {}, "uploaded": [], "preflight": {},
               "source_coverage": None}
    # All selected passages are processed only when the Live model explicitly
    # requested complete coverage. Partial retrieval is never called complete.
    if payload.get("source_ids"):
        from .work_corpus import analyze
        scope=await analyze(store,owner,payload["objective"],payload["source_ids"],
                            payload.get("source_coverage","targeted"),
                            payload.get("source_refs"))
        context["source_coverage"]=scope
        context["objective"]=(payload["objective"][:3000]+
            "\n\nSource evidence ("+scope["coverage"]+"):\n"+scope["text"][:5000])

    levels={}
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
                attempt = store.root / "attempts" / owner / jid / str(fence) / spec.name
                attempt.mkdir(parents=True, exist_ok=True, mode=0o700)
                from .work_reasoning import use
                with use(levels.get(spec.name,"medium")):
                    result = await asyncio.wait_for(invoke(spec, checkpoint, context, formats,
                             payload, store, owner, composer, researcher,
                             jid, worker_id, fence, attempt),
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
            inspections = result.get("inspections", {})
            if not isinstance(inspections, dict):
                raise ValueError("Malformed persisted artifact inspection receipts")
            for receipt in result_receipts(result):
                if receipt.kind in context["receipts"]:
                    raise ValueError("Duplicate output kind across specialists")
                inspected = inspections.get(receipt.kind)
                if inspected is not None:
                    if (not isinstance(inspected, dict) or
                        inspected.get("sha256") != receipt.sha256 or
                        not isinstance(inspected.get("quality"), dict) or
                        inspected["quality"].get("passed") is not True):
                        raise ValueError("Specialist QA does not match committed receipt")
                    context["preflight"][receipt.kind] = inspected
                context["receipts"][receipt.kind] = receipt
        return result

    graph = store.job_plan(owner,jid)
    dynamic = graph.get("schema_version")==2
    if dynamic and graph["status"]=="planning":
        from .work_dynamic import generate, WorkModelConfig
        proposed = await generate({**payload,"objective":context["objective"]},
                                  WorkModelConfig.from_env())
        graph=store.install_dynamic_graph(owner,jid,worker_id,fence,proposed)
    levels.update({step["id"]:step.get("thinking_level","medium") for step in graph["steps"]})
    if dynamic:
        from .work_agents import SPECS
        planned={node["id"]:SPECS[node["id"]] for node in graph["steps"]}
    else:
        # Historical V11 jobs only: retain their original plan and checkpoints.
        planned = {spec.name: spec for spec in plan(payload)}
    dependencies = {node["id"]: set(node["depends_on"]) for node in graph["steps"]}
    finished = set()

    semaphore = asyncio.Semaphore(2)  # Protect speech responsiveness on CPU hosts.

    async def stage_group(names):
        selected = [planned[name] for name in names if name in planned]
        if not selected:
            return
        async def bounded(spec):
            if not dependencies[spec.name].issubset(finished):
                raise ValueError("Unmet planned specialist dependency")
            async with semaphore:
                result = await run_agent(spec)
                finished.add(spec.name)
                return result
        # TaskGroup cancels and joins sibling tasks on failure. Native threads
        # continue only inside their isolated, fenced attempt directory.
        async with asyncio.TaskGroup() as group:
            for spec in selected:
                group.create_task(bounded(spec), name="specialist-" + spec.name)
        store.renew(jid, worker_id, fence, lease_seconds=45)

    def prepare_artifact_ir():
        """Compose the evidence-specific IR once prerequisites are complete."""
        if context["summary"]:
            summary=context["summary"]
            numeric=list(summary.get("numeric",{}).items())
            proof="\n".join([f"Rows: {summary['rows']}; duplicates: {summary['duplicates']}."]+
                [f"{name}: count {stats['count']}, mean {stats['mean']}, "
                 f"min {stats['min']}, max {stats['max']}."
                 for name,stats in numeric[:10]])
            context["text"]=(context["text"] or
                "# Dataset observations\nIndependent numeric analysis") + (
                "\n\n## Verified dataset evidence\n"+proof)
        context["artifact_ir"]=compile_ir(payload["objective"][:120],
            context["text"] or "# Analysis\nVerified dataset statistics",
            context["sources"],context["summary"])

    if dynamic:
        # Execute every currently ready node, not a hardcoded stage sequence.
        # Dependencies are supplied by the model, then independently validated.
        pending=set(planned)
        renderers=set(("powerpoint","word","excel","pdf_visual"))
        while pending:
            ready=[node["id"] for node in graph["steps"] if
                   node["id"] in pending and dependencies[node["id"]].issubset(finished)]
            if not ready:
                raise ValueError("Dynamic Work graph is stuck")
            if ((renderers.intersection(ready) or "quality" in ready) and
                    "artifact_ir" not in context):
                prepare_artifact_ir()
            await stage_group(ready)
            pending.difference_update(ready)
    else:
        # Read-only migration path for already accepted V11 DAGs.
        await stage_group(("research", "sql_analytics"))
        await stage_group(("orchestrator",))
        prepare_artifact_ir()
        await stage_group(("powerpoint", "word", "excel"))
        await stage_group(("pdf_visual",))
        await stage_group(("quality",))

    text = context["text"] or "# Verified analysis\nNo ungrounded model conclusions were generated."
    receipts = list(context["receipts"].values())
    store.finish(jid, worker_id, fence, text, receipts, checkpoint)


async def invoke(spec, checkpoint: Path, context: dict, formats: set[str],
                 payload: dict, store, owner, composer, researcher,
                 jid: str, worker_id: str, fence: int, attempt: Path):
    name = spec.name
    if name == "research":
        found = await researcher(payload["objective"])
        if isinstance(found, dict):
            if set(found).issuperset({"text","sources"}):
                return found
            raise ValueError("Research provider returned malformed evidence")
        text, sources = found
        return {"text": text, "sources": sources,
                "evidence_summary": {"citation_verification":"provider_attribution_only",
                                     "source_document_fetch":False}}
    if name == "sql_analytics":
        uploads = payload.get("uploads", [])
        if len(uploads) != 1:
            raise ValueError("SQL analysis requires exactly one uploaded dataset")
        source = store.upload(owner, uploads[0])
        return await asyncio.to_thread(analyze_sql, source)
    if name == "orchestrator":
        text = await composer(context["objective"], context["summary"])
        return {"text": text}
    if name == "quality":
        from .work_repair import validate_repair
        return await validate_repair(store,{"id":jid,"owner":owner,"fence":fence},
                                     worker_id,checkpoint,context,payload)
    if name not in ("powerpoint", "word", "excel", "pdf_visual"):
        raise ValueError("Unknown specialist")
    requested = sorted(formats.intersection(spec.formats))
    receipts = []
    inspections = {}
    from .work_quality import inspect_artifact
    from .work_visual import quality_mode
    strict = quality_mode() != "structural"
    # One independent format-specific renderer, reusing the existing vetted
    # document generation tools rather than duplicating their implementations.
    for kind in [x for x in requested if x != "zip"]:
        table = None
        if payload.get("uploads"):
            from .work_skills import read_dataset
            table = await asyncio.to_thread(read_dataset,
                                             store.upload(owner, payload["uploads"][0]))
        working = attempt / (kind + "." + kind)
        ir = context["artifact_ir"]
        dataset_rows = context["summary"]["rows"] if context["summary"] else None
        # Exactly one deterministic regeneration on a recoverable output
        # validation error; no additional model calls, user writes or tools.
        repairs = 0
        for attempt_no in range(2):
            await asyncio.to_thread(render_one, kind, working, ir.title,
                                    ir.content, table, list(ir.sources))
            try:
                report = await asyncio.to_thread(
                    inspect_artifact, working, kind, dataset_rows=dataset_rows,
                    artifact_ir=ir, dataset_summary=context["summary"],
                    visual_required=strict)
                break
            except ValueError:
                if attempt_no:
                    raise
                repairs += 1
                working.unlink(missing_ok=True)
        receipt = verify_artifact(working, kind)
        inspections[kind] = {"sha256":receipt.sha256,
                              "quality":report, "repair_attempts":repairs}
        promoted = store.agent_publish(jid, worker_id, fence, owner, working, receipt)
        if not verify_checkpoint(promoted, receipt):
            raise ValueError("Published specialist artifact failed checksum")
        receipts.append(receipt)
    if "zip" in requested:
        contents = list(context["receipts"].values()) + receipts
        if not contents:
            raise ValueError("ZIP requires a source output")
        working = attempt / "zip.zip"
        with zipfile.ZipFile(working, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in contents:
                archive.write(checkpoint / item.name, arcname=item.name)
            archive.writestr("MANIFEST.json", json.dumps(
                {"schema_version": 1, "files": [
                    {"name": r.name, "sha256": r.sha256, "bytes": r.byte_size}
                    for r in contents]}, indent=2))
        receipt = verify_artifact(working, "zip")
        promoted = store.agent_publish(jid, worker_id, fence, owner, working, receipt)
        if not verify_checkpoint(promoted, receipt):
            raise ValueError("Published archive failed checksum")
        receipts.append(receipt)
    return {"receipts": [asdict(r) for r in receipts],
            "inspections": inspections, "agent": name, "requested": requested}
