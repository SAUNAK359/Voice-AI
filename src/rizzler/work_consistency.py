"""V26 cross-artifact quantitative truth and provenance consistency gate.

Actual file text and editable chart series are inspected before an LLM maps
observed claims to immutable PCCF metric IDs. Only executable, source-bound
Decimal comparison decides truth. A model opinion is never accepted as a
numerical oracle, a source receipt, or evidence that a page was pixel-reviewed.
"""
from __future__ import annotations

from decimal import Decimal,InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re

from .cognitive_json import decode_model_json

SUPPORTED=frozenset({"pptx","docx","pdf","xlsx"})
MAX_SOURCE_CHARS=32_000
MAX_METRICS=40
NUMERIC=re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?%?(?![\w.])")


class ConsistencyViolation(ValueError):
    """Quantitative claims across output artifacts do not reconcile."""


def _number(value) -> Decimal:
    if isinstance(value,bool) or value is None:
        raise ConsistencyViolation("Missing numerical value")
    try:
        candidate=Decimal(str(value).replace(",",""))
    except (InvalidOperation,TypeError,ValueError) as exc:
        raise ConsistencyViolation("Unparseable reported numerical value") from exc
    if not candidate.is_finite():
        raise ConsistencyViolation("Nonfinite quantitative claim")
    return candidate


def metric_catalog(graph: dict) -> dict:
    """Only source-bound computed/verified metrics are comparison oracles."""
    from .work_context_fabric import validate_fabric
    # validate_fabric is the authoritative v26 graph checker.
    authoritative=validate_fabric(graph)
    catalog={}
    for node in authoritative["nodes"]:
        if node["kind"]!="metric" or node["status"] not in (
                "computed_summary","verified"):
            continue
        data=node["data"]
        if data.get("critical") is not True:
            continue
        if (not isinstance(data.get("unit"),str) or
                not data["unit"].strip() or
                not isinstance(data.get("period"),str) or
                not data["period"].strip()):
            raise ConsistencyViolation("Critical metric lacks unit or period")
        if not isinstance(data.get("source_table_sha256"),str):
            raise ConsistencyViolation("Critical metric lacks table lineage")
        catalog[node["id"]]={
            "metric_id":node["id"],
            "value":str(_number(data["value"])),
            "unit":data["unit"],
            "period":data["period"],
            "source_sha256":data["source_table_sha256"],
            "name":data["name"]}
        if len(catalog)>MAX_METRICS:
            raise ConsistencyViolation("Too many critical numeric obligations")
    return catalog


def extracted_artifact_text(path: Path,kind: str) -> str:
    """Read the actual file structure; never trust an agent's own summary."""
    if kind not in SUPPORTED:
        raise ConsistencyViolation("Unsupported output for claim audit")
    path=Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size>50_000_000:
        raise ConsistencyViolation("Invalid artifact input")
    chunks=[]
    if kind=="pptx":
        from pptx import Presentation
        deck=Presentation(path)
        for index,slide in enumerate(deck.slides):
            chunks.append(f"SLIDE {index+1}:")
            for shape in slide.shapes:
                if shape.has_text_frame:
                    chunks.append(shape.text)
                if shape.has_chart:
                    chart=shape.chart
                    for series in chart.series:
                        # Actual editable Office chart values, not model prose.
                        values=[]
                        for value in series.values:
                            if value is None:
                                continue
                            values.append(str(_number(value)))
                        chunks.append("EDITABLE_CHART_SERIES "+str(series.name)+
                                      " = "+", ".join(values))
    elif kind=="docx":
        from docx import Document
        doc=Document(path)
        chunks.extend(p.text for p in doc.paragraphs)
        for table in doc.tables:
            for row in table.rows:
                chunks.append(" | ".join(cell.text for cell in row.cells))
    elif kind=="pdf":
        import fitz
        with fitz.open(path) as doc:
            chunks=[page.get_text() for page in doc]
    elif kind=="xlsx":
        from openpyxl import load_workbook
        wb=load_workbook(path,read_only=True,data_only=False)
        try:
            for sheet in wb:
                chunks.append("WORKSHEET "+sheet.title)
                for row in sheet.iter_rows(min_row=1,max_row=min(sheet.max_row,200),
                                           max_col=min(sheet.max_column,35)):
                    chunks.append(" | ".join(
                        str(cell.value)[:250] if cell.value is not None else ""
                        for cell in row))
        finally:
            wb.close()
    full="\n".join(chunks)
    if not full.strip():
        raise ConsistencyViolation("Artifact contains no inspectable content")
    if len(full)>MAX_SOURCE_CHARS:
        # Never claim to have reviewed a long artifact after silently
        # discarding its later pages, tables, or numerical conclusions.
        raise ConsistencyViolation(
            "Artifact text exceeds complete-review budget; split into "
            "independently reviewable components before certification")
    return full


def validate_claim_report(report: object, *, catalog: dict,
                          source_text: str,kind: str) -> dict:
    """Every model-extracted claim must point to source-visible evidence."""
    if kind not in SUPPORTED or not isinstance(report,dict) or set(report)!={
            "schema_version","artifact_kind","claims","assessment"}:
        raise ConsistencyViolation("Invalid claim audit envelope")
    claims=report["claims"]
    if (report["schema_version"]!=1 or report["artifact_kind"]!=kind
            or not isinstance(claims,list) or len(claims)>MAX_METRICS
            or not isinstance(report["assessment"],str)
            or not 10<=len(report["assessment"])<=500):
        raise ConsistencyViolation("Invalid claim audit schema or budget")
    seen={}
    verified=[]
    for claim in claims:
        if not isinstance(claim,dict) or set(claim)!={
                "metric_id","value","unit","period","observed_excerpt"}:
            raise ConsistencyViolation("Incorrect claim fields")
        key=claim["metric_id"]
        if key not in catalog:
            raise ConsistencyViolation("Model invented a critical metric identity")
        original=catalog[key]
        excerpt=claim["observed_excerpt"]
        if (not isinstance(excerpt,str) or not 5<=len(excerpt)<=500
                or excerpt not in source_text):
            raise ConsistencyViolation("No observable artifact evidence for model claim")
        if _number(claim["value"])!=_number(original["value"]):
            raise ConsistencyViolation("Reported metric disagrees with verified source")
        if claim["unit"]!=original["unit"] or claim["period"]!=original["period"]:
            raise ConsistencyViolation("Metric units or reporting scope drifted")
        number_tokens=[x.replace(",","").rstrip("%")
                       for x in NUMERIC.findall(excerpt)]
        if _number(claim["value"]) not in {_number(x) for x in number_tokens}:
            raise ConsistencyViolation("Claimed number is absent from cited artifact text")
        if key in seen and seen[key]!=claim:
            raise ConsistencyViolation("Contradictory duplicate metric observation")
        seen[key]=claim
        verified.append(key)
    return {"passed":True,"verified_ids":sorted(set(verified)),
            "unobserved_critical_ids":sorted(set(catalog)-set(verified)),
            "limitations":"Extraction is LLM-assisted; this gate proves only "
                "the checked source-bound numerical claims, not every "
                "possible fact or visual assertion."}


async def audit_artifact_claims(path: Path,kind: str,graph: dict,
                                *,model: str,api_key: str,
                                client=None) -> dict:
    """Independent reviewer maps observed source text to canonical metrics."""
    catalog=metric_catalog(graph)
    if not catalog:
        return {"passed":True,"verified_ids":[],"unobserved_critical_ids":[],
                "status":"no_critical_numeric_obligations"}
    if not api_key:
        raise ConsistencyViolation("Live quantitative reviewer unavailable")
    source_text=extracted_artifact_text(path,kind)
    owned=client is None
    if owned:
        from google import genai
        client=genai.Client(api_key=api_key)
    from google.genai import types
    from .cognitive_provider import generate_with_recovery
    prompt=(
        "You are a skeptical independent quantitative CLAIM EXTRACTOR. "
        "Read the actual generated artifact's extracted text and editable "
        "native chart series. Identify ONLY explicitly OBSERVED numeric "
        "claims that correspond to the approved canonical metrics. "
        "Never invent a claim or an excerpt. For each claim, copy an EXACT "
        "5–500 character contiguous source excerpt that visibly includes "
        "the reported numeric value. If a critical metric is not directly "
        "observable, omit it; the runtime will report it as unobserved. "
        "For source unit and period, use the exact canonical labels; do not "
        "guess missing units, periods or currencies. No private reasoning. "
        "Return JSON EXACTLY: "
        '{"schema_version":1,"artifact_kind":"'+kind+
        '","claims":[{"metric_id":"metric:comparison_total_first",'
        '"value":"600","unit":"unspecified","period":"observed",'
        '"observed_excerpt":"verbatim observed artifact excerpt"}],'
        '"assessment":"brief reviewer coverage statement"}. '
        "Only use the actual approved metric IDs and numerical values; do "
        "not infer metrics from an unrelated number. "
        "\nCanonical checked metric catalog:\n"+
        json.dumps(list(catalog.values()),ensure_ascii=False)[:9000]+
        "\nActual inspected file content:\n"+source_text)
    try:
        for attempt in range(2):
            response=await generate_with_recovery(
                client,role="work",model=model,timeout=85,
                contents=prompt+(
                    "\nPrior JSON invalid. Return only observable, source-exact "
                    "claims; no unsupported IDs or quoted lines."
                    if attempt else ""),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=.1,max_output_tokens=2200))
            try:
                data=decode_model_json(
                    getattr(response,"text","") or "",max_bytes=15000)
                return validate_claim_report(
                    data,catalog=catalog,source_text=source_text,kind=kind)
            except (ValueError,TypeError,KeyError) as exc:
                if attempt:
                    raise ConsistencyViolation(
                        "Model could not provide a trustworthy claim audit") from exc
    finally:
        if owned:
            await client.aio.aclose()


def reconcile_claim_reports(reports: dict[str,dict]) -> dict:
    """All approved source-backed claims have one canonical cross-format truth."""
    if not isinstance(reports,dict):
        raise ConsistencyViolation("Malformed cross-artifact QA set")
    if not reports:
        return {"passed":False,"verified_metric_appearances":{},
                "missing_required_metrics":[],
                "limitations":"No supported artifact was independently inspected"}
    checked={}
    for kind,report in reports.items():
        if kind not in SUPPORTED or not isinstance(report,dict) or not report.get("passed"):
            raise ConsistencyViolation("Unverified artifact claim report")
        for key in report.get("verified_ids",[]):
            checked.setdefault(key,[]).append(kind)
    missing=sorted(set().union(
        *(set(item.get("unobserved_critical_ids",[]))
          for item in reports.values()))-set(checked))
    return {"passed":not missing,
            "verified_metric_appearances":checked,
            "missing_required_metrics":missing,
            "limitations":"Cross-format consistency is bounded by the actual "
                "source-backed metrics that were extracted and verified."}
