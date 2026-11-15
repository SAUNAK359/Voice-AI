"""Model-authored Work graphs with deterministic capability and data-contract checks.

There are no objective keyword heuristics, default stage recipes, or silent
fallback DAGs. Provider failure leaves the accepted job failed/retryable, never
misreports a template as autonomous planning.
"""
from __future__ import annotations
import asyncio
import json
from .contracts import FILE_FORMATS
from .production_guard import reserve_provider_call
from .work_agents import SPECS

from dataclasses import dataclass
from os import environ
import re

@dataclass(frozen=True)
class WorkModelConfig:
    """Work's provider configuration is not a second user authentication."""
    gemini_api_key: str
    gemini_model: str
    request_timeout: float

    @classmethod
    def from_env(cls):
        from .config import Settings
        model=environ.get("RIZZLER_GEMINI_MODEL",Settings.__dataclass_fields__["gemini_model"].default)
        timeout=float(environ.get("RIZZLER_WORK_MODEL_TIMEOUT","45"))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,99}",model) or not 10<=timeout<=180:
            raise ValueError("Invalid Work model configuration")
        return cls(environ.get("GEMINI_API_KEY",""),model,timeout)

VERSION=2
PRODUCERS={name: set(spec.formats) for name,spec in SPECS.items() if spec.formats}
CONTENT=frozenset(("research","orchestrator"))
EVIDENCE=frozenset(("research","sql_analytics"))

def pending() -> dict:
    return {"schema_version": VERSION, "status": "planning", "steps": []}

def validate(graph: dict, payload: dict) -> dict:
    """Validate what the agents proposed, never decide the plan for them."""
    if type(graph) is not dict or set(graph) != {"schema_version","status","steps"}:
        raise ValueError("Malformed dynamic Work graph")
    if graph["schema_version"] != VERSION or graph["status"] not in ("planning","ready"):
        raise ValueError("Unsupported Work graph")
    steps=graph["steps"]
    if graph["status"]=="planning":
        if steps: raise ValueError("Planning graph must be empty")
        return graph
    if type(steps) is not list or not 2<=len(steps)<=len(SPECS):
        raise ValueError("Plan must contain bounded distinct tools")
    by_name={}
    for item in steps:
        if type(item) is not dict or not {"id","tool","depends_on"}.issubset(item) or set(item)-{"id","tool","depends_on","thinking_level"}:
            raise ValueError("Plan step schema mismatch")
        if "thinking_level" in item and item["thinking_level"] not in ("medium","high"):
            raise ValueError("Unrecognized Gemini thinking level")
        name=item["id"]
        if type(name) is not str or name != item["tool"] or name not in SPECS or name in by_name:
            raise ValueError("Unregistered or duplicated capability")
        deps=item["depends_on"]
        if type(deps) is not list or any(type(d) is not str for d in deps) or len(deps)!=len(set(deps)):
            raise ValueError("Invalid dependency list")
        by_name[name]=deps
    completed=set()
    for item in steps:
        deps=by_name[item["id"]]
        if not set(deps).issubset(completed):
            raise ValueError("Graph contains forward, unknown or cyclic dependencies")
        completed.add(item["id"])
    if "quality" not in by_name or set(by_name["quality"]) != set(by_name)-{"quality"}:
        raise ValueError("Independent quality gate must depend on every other step")
    outputs=set(payload["deliverables"]) & FILE_FORMATS
    union=set().union(*(PRODUCERS.get(name,set()) for name in by_name))
    if not outputs.issubset(union):
        raise ValueError("Model omitted required artifact capability")
    for name in by_name:
        supported=PRODUCERS.get(name)
        if supported is not None and not supported.intersection(outputs):
            raise ValueError("Model proposed unnecessary artifact capability")
    uploads=payload.get("uploads") or []
    if len(uploads)>1:
        raise ValueError("The registered dataset tool supports one dataset")
    if ("sql_analytics" in by_name) != bool(uploads):
        raise ValueError("Source dataset must be analyzed; no imaginary dataset")
    if "data_analysis" in payload["deliverables"] and not uploads:
        raise ValueError("Analysis requires an uploaded dataset")
    if payload.get("evidence_scope","auto")=="uploaded_only" and "research" in by_name:
        raise ValueError("Uploaded-only evidence scope forbids external research")
    if payload.get("evidence_scope","auto")=="uploaded_only" and "research" in payload["deliverables"]:
        raise ValueError("Research deliverable incompatible with uploaded-only evidence scope")
    needs_narrative=bool(set(payload["deliverables"]) & {"md","docx","pdf","pptx","html","txt"})
    if (needs_narrative and payload.get("evidence_scope")=="uploaded_only"
            and "orchestrator" not in by_name):
        raise ValueError("Narrative deliverables require evidence-aware content synthesis")
    if "research" in payload["deliverables"] and "research" not in by_name:
        raise ValueError("Requested grounded research is missing")
    if not CONTENT.intersection(by_name) and not uploads:
        raise ValueError("No source of report content")
    if "orchestrator" in by_name and not set(by_name["orchestrator"]).issuperset(
            EVIDENCE.intersection(by_name)):
        raise ValueError("Content synthesis must see all gathered evidence")
    # Every rendering specialist consumes the content/data sources that were
    # selected. These are data dependencies, not a hardcoded execution order.
    for name in PRODUCERS.keys() & by_name.keys():
        if not (CONTENT | EVIDENCE).intersection(by_name[name]):
            raise ValueError("Renderer has no evidence or content predecessor")
        required = set((CONTENT | EVIDENCE).intersection(by_name.keys()))
        if "orchestrator" in required:
            required -= {"research","sql_analytics"}
            required.add("orchestrator")
        if not required.issubset(by_name[name]):
            raise ValueError("Rendering must wait for its selected inputs")
    if "zip" in outputs:
        if outputs == {"zip"}:raise ValueError("ZIP needs at least one other artifact")
        zip_step=next((name for name in by_name
                       if "zip" in PRODUCERS.get(name,set())),None)
        if not zip_step or not set(name for name in by_name if name in PRODUCERS
                                   and name!=zip_step).issubset(by_name[zip_step]):
            raise ValueError("ZIP must wait for other artifacts")
    return graph


class PlanningOutputError(ValueError):
    """Gemini failed to provide a valid, executable model-authored Work graph."""


def _graph_json_schema():
    """Provider-level shape constraint; validate() still enforces the DAG semantics."""
    capabilities=sorted(SPECS)
    step={
        "type":"object",
        "properties":{
            "id":{"type":"string","enum":capabilities},
            "tool":{"type":"string","enum":capabilities},
            "depends_on":{"type":"array","items":{"type":"string","enum":capabilities}},
            "thinking_level":{"type":"string","enum":["medium","high"]},
        },
        "required":["id","tool","depends_on","thinking_level"],
        "additionalProperties":False,
    }
    return {
        "type":"object",
        "properties":{
            "schema_version":{"type":"integer","enum":[VERSION]},
            "status":{"type":"string","enum":["ready"]},
            "steps":{"type":"array","items":step,"minItems":2,"maxItems":len(SPECS)},
        },
        "required":["schema_version","status","steps"],
        "additionalProperties":False,
    }


def _response_graph(response):
    """Accept only one structured graph, never scrape partial JSON from model prose."""
    parsed=getattr(response,"parsed",None)
    if parsed is not None:
        if hasattr(parsed,"model_dump"):
            parsed=parsed.model_dump()
        if type(parsed) is not dict:
            raise ValueError("Model structured output is not an object")
        return parsed
    raw=(getattr(response,"text","") or "").strip()
    if not 30<=len(raw)<=18000:
        raise ValueError("Empty or oversized model graph")
    # Strict decoding deliberately rejects markdown fences and multiple JSON values.
    parsed=json.loads(raw)
    if type(parsed) is not dict:
        raise ValueError("Model graph must be a JSON object")
    return parsed


async def generate(payload: dict, settings, *, client=None) -> dict:
    """Gemini-authored DAG, provider schema + semantic gate + bounded self-repair."""
    if not settings.gemini_api_key and client is None:
        raise RuntimeError("Agentic Work planning requires a configured model")
    own=client is None
    if own:
        from google import genai
        client=genai.Client(api_key=settings.gemini_api_key)
    from google.genai import types
    tools=[{"name":k,"role":s.role,"formats":s.formats,
            "target_seconds":s.sla_seconds} for k,s in SPECS.items()]
    instruction=(
        "Design an executable dependency DAG for this user objective. "
        "Use registered capabilities only and select the necessary ones, not a fixed recipe. "
        "External research is appropriate only if independent current evidence is needed. "
        "A dataset must be analyzed when one is attached. "
        "If evidence_scope is uploaded_only, do not use external research under any circumstance; "
        "the supplied data is the only authorized evidence. If it is auto, reason "
        "from the user's full objective and explicit prohibitions; do not infer "
        "the need for web evidence merely from report complexity. "
        "Narrative deliverables (Markdown, Word, PDF, PowerPoint, text, HTML) "
        "require an orchestrator to turn analysis into a substantive report. "
        "The id and tool values of each step must be the same registered capability. "
        "Every capability can appear at most once. Dependency edges refer only to "
        "earlier steps. The final quality step is mandatory and depends on all others. "
        "Renderers must wait for their model-selected evidence and synthesis inputs; "
        "a ZIP must depend on all other produced formats. "
        "Choose medium or high thinking individually for each step according to "
        "uncertainty and verification needs, not superficial keywords. "
        "Produce only the requested structured graph. "
        "Available capabilities: "+json.dumps(tools,separators=(",",":"))+
        "\nRequested deliverables: "+json.dumps(payload["deliverables"])+
        "\nEvidence scope: "+json.dumps(payload.get("evidence_scope","auto"))+
        "\nDataset attached: "+str(bool(payload.get("uploads")))+
        "\nUntrusted user objective: "+json.dumps(payload["objective"][:8000]))
    schema=_graph_json_schema()
    last_problem="unknown"
    try:
        for attempt in range(3):
            feedback=("" if attempt==0 else
                "\nThe last graph was rejected by the execution contract ("+
                last_problem+"). Choose a corrected DAG; never add unsupported tools "
                "or omit required dependencies.")
            reserve_provider_call("work")
            async with asyncio.timeout(min(28,settings.request_timeout)):
                response=await client.aio.models.generate_content(
                    model=settings.gemini_model,contents=instruction+feedback,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=2500,
                        response_mime_type="application/json",
                        response_json_schema=schema))
            try:
                return validate(_response_graph(response),payload)
            except (ValueError,TypeError,json.JSONDecodeError) as exc:
                # Avoid storing raw model text (potentially user data/secrets).
                # Class name is sufficient to drive a model correction attempt.
                last_problem=type(exc).__name__
        raise PlanningOutputError("Gemini returned no valid Work DAG after 3 attempts")
    finally:
        if own:
            await client.aio.aclose()
