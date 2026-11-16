"""MCP-backed grounded retrieval using the same model-led research director.

Only the operator-approved read-only MCP research tool can be invoked.
Neither MCP citations nor the model's answer are promoted to verified primary
source truth without independent inspection.
"""
from __future__ import annotations

import asyncio
import os

from .work_mcp import configured, invoke


class MCPEvidenceMissing(RuntimeError):
    """Selected MCP source did not substantiate the requested research."""


def research_tool() -> str | None:
    identifier = os.environ.get("RIZZLER_MCP_RESEARCH_TOOL","").strip()
    if not identifier:
        return None
    spec = configured().get(identifier)
    if spec is None or spec.arguments != {"query":"str"}:
        raise ValueError("MCP research requires an approved query-only read tool")
    return identifier


async def research(objective: str, cfg, *, client=None, max_rounds=3) -> dict:
    """LLM chooses the questions, MCP fetches results, evidence gate decides."""
    from .work_cognition import direct_research
    identifier=research_tool()
    if identifier is None:
        raise ValueError("No approved MCP research provider configured")
    findings=[]
    evidence={}
    events=[]
    covered=False
    for step in range(max_rounds):
        direction=await direct_research(
            objective,cfg,rounds_remaining=max_rounds-step,
            evidence=list(evidence.values()),observations=events,
            client=client)
        events.append({"round":step+1,"action":direction.action})
        if direction.action=="block":
            raise MCPEvidenceMissing("research_director_blocked_insufficient_evidence")
        if direction.action=="finish":
            covered=True
            break
        answers=await asyncio.gather(*[
            invoke(identifier,{"query":question})
            for question in direction.questions],
            return_exceptions=True)
        for question,outcome in zip(direction.questions,answers):
            if isinstance(outcome,Exception):
                events.append({"round":step+1,"status":"provider_error",
                               "error_code":type(outcome).__name__[:60]})
                continue
            urls=outcome["sources"]
            body=outcome["text"].strip()
            if not urls or len(body)<45:
                events.append({"round":step+1,"status":"no_grounded_evidence",
                               "source_count":len(urls)})
                continue
            for url in urls:
                evidence.setdefault(url,{"url":url,"title":"",
                                        "publisher":url.split("/")[2],
                                        "content_verified":False})
            findings.append("## Model-selected research question\n"+question+
                            "\n\n"+body[:7500])
            events.append({"round":step+1,"status":"attributed",
                           "source_count":len(urls)})
    if not findings or not evidence:
        raise MCPEvidenceMissing("mcp_search_found_no_attributable_sources")
    urls=list(evidence)[:24]
    return {"text":"# MCP-attributed research\n\n"+"\n\n".join(findings)+
            "\n\n## Provenance limitation\nMCP links are tool-provided attributions, "
            "not independently fetched or fact-checked primary documents. "
            "URLs:\n"+"\n".join("- "+url for url in urls),
            "sources":urls,
            "evidence":list(evidence.values())[:24],
            "evidence_summary":{"provenance":"configured_read_only_mcp",
                                "citation_verification":"tool_attribution_only",
                                "source_document_fetch":False,
                                "grounded_queries":len(findings),
                                "model_coverage_accepted":covered,
                                "attempts":events},
            "partial":not covered}
