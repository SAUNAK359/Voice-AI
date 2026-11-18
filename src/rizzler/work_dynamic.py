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
    if ("data_analysis" in payload["deliverables"] and not uploads
            and ("research" not in by_name or
                 payload.get("evidence_scope")=="uploaded_only")):
        raise ValueError("Analysis requires an uploaded or externally sourced dataset")
    if payload.get("evidence_scope","auto")=="uploaded_only" and "research" in by_name:
        raise ValueError("Uploaded-only evidence scope forbids external research")
    if payload.get("evidence_scope","auto")=="uploaded_only" and "research" in payload["deliverables"]:
        raise ValueError("Research deliverable incompatible with uploaded-only evidence scope")
    needs_narrative=bool(set(payload["deliverables"]) & {"md","docx","pdf","pptx","html","txt"})
    if (needs_narrative and payload.get("evidence_scope")=="uploaded_only"
            and "orchestrator" not in by_name):
        raise ValueError("Narrative deliverables require evidence-aware content synthesis")
    if payload.get("evidence_scope") == "external_allowed" and "research" not in by_name:
        raise ValueError("Explicit external research scope requires a research specialist")
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
    """Gemini-authored plan, with complete cognitive preflight when enabled.

    Legacy graph-generation remains available as a compatibility adapter;
    it is never selected when preflight explicitly fails.
    """
    # Deep Agents is opt-in until the new runtime passes live acceptance.
    # The WorkStore remains the ONLY durable job and publication authority.
    orchestration = __import__("os").environ.get(
        "RIZZLER_WORK_ORCHESTRATOR", "legacy").strip().lower()
    if orchestration == "deepagents":
        from .work_sglang import enabled as local_work
        if local_work():
            # Preserve the V17 on-premise Deep Agents implementation.
            from .work_deepagents import plan_with_deepagents
            return await plan_with_deepagents(payload,settings,client=client)
        if client is not None:
            # Existing injected clients preserve the explicit test adapter.
            from .work_deepagents import plan_with_deepagents
            return await plan_with_deepagents(payload, settings, client=client)
        from .work_gemini_gateway import gemini_content, WorkProviderUnavailable
        from .work_deepagents import plan_with_deepagents
        # One model-authored structured decision is substantially cheaper than
        # an entire recursive supervisor run, while retaining the same strict
        # dependency, evidence and artifact contracts. The model still selects
        # every specialist and dependency (never keyword-based routing).
        from .work_skill_packages import load_package
        capabilities=[{"name":name,"role":spec.role,
                       "formats":list(spec.formats),
                       "capabilities":list(load_package(name).capabilities)}
                      for name,spec in SPECS.items()]
        instruction=(
            "You are Rizzler's autonomous Work supervisor. Return ONE complete "
            "valid, topologically ordered DAG, selected based on the entire "
            "objective. Maximize useful planning in one response. Include "
            "required external research when evidence_scope=external_allowed, "
            "include sql_analytics exactly when an uploaded dataset exists, "
            "include an orchestrator for narrative synthesis, and choose "
            "model-specialist capabilities for every requested output. "
            "Every renderer depends on selected evidence or synthesis, and "
            "ZIP waits for other artifact renderers. Quality is final and "
            "depends on ALL preceding steps. Do not invent source datasets. "
            "Only registered capabilities and medium/high thinking levels. "
            "Never invent file receipts. Return exact schema_version=2, "
            "status=ready and steps with id=tool, depends_on,thinking_level. "
            "Your model decisions are subject to independent validation. "
            "\nCapability catalog: "+json.dumps(capabilities,separators=(',',':'))+
            "\nTask: "+json.dumps({
                "objective":payload["objective"][:8000],
                "deliverables":payload["deliverables"],
                "dataset_attached":bool(payload.get("uploads")),
                "evidence_scope":payload.get("evidence_scope","auto"),
                "sources_attached":bool(payload.get("source_ids"))},
                ensure_ascii=False,separators=(',',':')))
        problem=None
        for attempt in range(2):
            try:
                response=await gemini_content(
                    settings,
                    instruction+("" if problem is None else
                        "\nPrevious graph rejected: "+problem+
                        ". Repair precisely; return full corrected graph."),
                    schema=_graph_json_schema(),max_output_tokens=3600)
                graph=_response_graph(response)
                return validate(graph,payload)
            except WorkProviderUnavailable:
                # Both authorized Gemini models exhausted: defer rather than
                # spawning another multi-call supervisor against the outage.
                raise
            except (ValueError,TypeError,json.JSONDecodeError,KeyError) as exc:
                # Safe local validator feedback, not raw private model output.
                problem=type(exc).__name__+":" + str(exc)[:150]
        # Complex model plans that cannot satisfy the structured contract
        # enter the Deep Agents multi-tool supervisor as a bounded escalation,
        # never on a provider outage. This preserves genuine agentic replanning.
        return await plan_with_deepagents(payload,settings)
    if orchestration != "legacy":
        raise ValueError("Unsupported Work orchestration backend")
    from .work_preflight import enabled as cognitive_enabled, generate_preflight
    # Worker claims always carry fenced context. Direct calls with a supplied
    # model client but without a job remain the legacy planning adapter.
    durable = payload.get("_cognitive_checkpoint")
    if cognitive_enabled() and (durable is not None or client is None):
        if durable is not None:
            store, owner, jid, worker, fence = durable
            previous = store.cognitive_preflight(owner, jid)
            if previous is not None:
                from .work_preflight import verify_committed
                return verify_committed(previous, payload)["plan"]
        def record_feedback(attempt, code):
            store.record_cognitive_feedback(owner,jid,worker,fence,attempt,code)
        document = await generate_preflight(
            payload,settings,client=client,
            on_feedback=record_feedback if durable is not None else None)
        if durable is not None:
            store.install_cognitive_preflight(owner, jid, worker, fence, document)
        return document["plan"]
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
            from .work_async import wait_scope
            async with wait_scope(min(28,settings.request_timeout)):
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
