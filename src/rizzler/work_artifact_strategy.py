"""V26 audience-first PowerPoint strategy over source-preserving editorial IR.

The model decides what belongs in the audience-facing argument. Existing
PowerPoint renderer and bounded component recovery remain the actual file
writers; this module does not mint source evidence or hide excluded sections.
"""
from __future__ import annotations

from dataclasses import replace


async def create_editorial_storyboard(objective: str,ir, *,
                                      model: str,api_key: str,
                                      checkpoint,client=None,
                                      progress=None) -> dict:
    from .work_editorial_director import create_editorial_plan
    from .work_studio import create_storyboard,validate_storyboard
    from .v23_flags import enabled as v25_enabled
    from .work_incremental_studio import create_incremental_storyboard

    owned=client is None
    if owned:
        from google import genai
        client=genai.Client(api_key=api_key)
    try:
        editorial=await create_editorial_plan(
            objective,ir,model=model,api_key=api_key,client=client)
        selected=tuple(editorial["selected_section_ids"])
        if len(set(selected))!=len(selected):
            raise ValueError("Editorial section selection duplicated source identity")
        scoped=replace(ir,sections=tuple(ir.sections[i] for i in selected))
        # Only source section IDs are remapped. Original evidence remains
        # authoritative, and no generated claim is promoted to source truth.
        strategy=(
            objective[:3000]+
            "\nEditorial objective: "+editorial["purpose"]+
            "\nNarrative thesis: "+editorial["thesis"]+
            "\nAudience: "+editorial["audience"]+
            "\nRelevant limitations: "+
            "; ".join(editorial["limitations"])[:2800]+
            "\nProduce a concise, insightful presentation, not a report dump. "
            "Do not include excluded sections, internal implementation "
            "methods or system packaging unless the user requested those. "
            "Provide specific findings and avoid repeated metrics or charts.")
        if v25_enabled("RIZZLER_COMPONENT_PLANNING") and len(selected)>=4:
            local=await create_incremental_storyboard(
                strategy,scoped,model=model,api_key=api_key,
                client=client,checkpoint=checkpoint,progress=progress)
        else:
            local=await create_storyboard(
                strategy,scoped,model=model,api_key=api_key,client=client,
                min_slides=1,max_slides=36)
        slides=[]
        for slide in local["slides"]:
            item=dict(slide)
            item["section_ids"]=[selected[i] for i in slide["section_ids"]]
            slides.append(item)
        final={
            "schema_version":1,
            "slides":slides,
            "sections_covered":sorted(
                {x for slide in slides for x in slide["section_ids"]}),
            "editorial_plan":editorial,
        }
        return validate_storyboard(
            final,ir.sections,ir.sources,
            min_slides=1,max_slides=36,allow_editorial=True)
    finally:
        if owned:
            await client.aio.aclose()
