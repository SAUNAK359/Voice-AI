"""V26 editable, source-bound chart strategy; the LLM chooses meaning.

Never select "first numeric column" merely because a slide says metrics.
Charts are composed only from actual uploaded table columns or one approved
typed arithmetic derivation. Repeated chart semantics fail qualification.
"""
from __future__ import annotations

from decimal import Decimal
import json
import math

from .cognitive_json import decode_model_json


class VisualStrategyError(ValueError):
    """A chart cannot be linked to the actual user evidence and slide claim."""


def _num(value):
    if isinstance(value,bool) or value is None:
        raise VisualStrategyError("Missing numeric chart point")
    try:
        d=Decimal(str(value))
    except Exception as exc:
        raise VisualStrategyError("Chart point cannot be parsed numerically") from exc
    if not d.is_finite():
        raise VisualStrategyError("Non-finite chart value")
    return d


def validate_visual_plan(plan: dict,blueprint: dict,table) -> dict:
    if (not isinstance(plan,dict) or set(plan)!={
            "schema_version","slides"} or plan["schema_version"]!=2):
        raise VisualStrategyError("Invalid visual plan schema")
    if (not isinstance(plan["slides"],list) or
            len(plan["slides"])!=len(blueprint["slides"])):
        raise VisualStrategyError("Visual plan not aligned to approved slides")
    headers,rows=table
    if (not isinstance(headers,(list,tuple)) or
            len(set(headers))!=len(headers) or not rows):
        raise VisualStrategyError("No independent source table for visuals")
    unique=set()
    for i,item in enumerate(plan["slides"]):
        if (not isinstance(item,dict) or set(item)!={
                "slide_index","visual_type","category_column","series_columns",
                "difference","claim_binding","reason"}
                or item["slide_index"]!=i or
                item["visual_type"] not in ("none","bar","line")
                or not isinstance(item["reason"],str)
                or not 16<=len(item["reason"].strip())<=450):
            raise VisualStrategyError("Malformed per-slide visual selection")
        if item["visual_type"]=="none":
            if any((item["category_column"] is not None,
                    item["series_columns"]!=[],
                    item["difference"] is not None,
                    item["claim_binding"] is not None)):
                raise VisualStrategyError("Non-chart slide claimed data bindings")
            continue
        x=item["category_column"]
        y=item["series_columns"]
        derived=item["difference"]
        binding=item["claim_binding"]
        if (not isinstance(x,str) or x not in headers
                or not isinstance(y,list) or not 1<=len(y)<=3
                or len(set(y))!=len(y)
                or any(not isinstance(name,str) or
                       name not in headers or name==x for name in y)):
            raise VisualStrategyError("Chart references invented source column")
        actual_series=set(y)
        if derived is not None:
            if (not isinstance(derived,dict) or set(derived)!={
                    "operation","left_column","right_column","label"}
                    or derived["operation"]!="subtract"
                    or derived["left_column"] not in headers
                    or derived["right_column"] not in headers
                    or derived["left_column"]==derived["right_column"]
                    or not isinstance(derived["label"],str)
                    or not 3<=len(derived["label"])<=80):
                raise VisualStrategyError("Unapproved or non-editable derivation")
            actual_series.add(derived["label"])
        if binding not in actual_series:
            raise VisualStrategyError("Chart does not show its asserted primary metric")
        for row in rows:
            if len(row)!=len(headers):
                raise VisualStrategyError("Source table row mismatch")
            for name in y:
                _num(row[headers.index(name)])
            if derived is not None:
                _num(row[headers.index(derived["left_column"])])
                _num(row[headers.index(derived["right_column"])])
        identity=(x,tuple(sorted(y)),
                  None if derived is None else (
                      derived["operation"],
                      derived["left_column"],derived["right_column"]))
        if identity in unique:
            raise VisualStrategyError(
                "Duplicate chart series and category encoding without new evidence")
        unique.add(identity)
    return plan


def chart_values(item: dict,table) -> tuple[list[str],dict[str,list[float]]]:
    headers,rows=table
    x=headers.index(item["category_column"])
    categories=[str(row[x])[:80] for row in rows[:36]]
    values={}
    for field in item["series_columns"]:
        index=headers.index(field)
        values[field]=[float(_num(row[index])) for row in rows[:36]]
    if item["difference"]:
        d=item["difference"]
        a=headers.index(d["left_column"])
        b=headers.index(d["right_column"])
        values[d["label"]]=[
            float(_num(row[a])-_num(row[b])) for row in rows[:36]]
    if not values:
        raise VisualStrategyError("No usable chart series")
    return categories,values


async def create_visual_plan(objective: str,blueprint: dict,table, *,
                             model: str,api_key: str,client=None) -> dict:
    if not api_key:
        raise VisualStrategyError("Visual strategy needs an authorized model")
    owned=client is None
    if owned:
        from google import genai
        client=genai.Client(api_key=api_key)
    from google.genai import types
    from .cognitive_provider import generate_with_recovery
    headers,rows=table
    slides=[{"slide_index":i,"title":s["title"],
             "message":s["message"],"kind":s["kind"]}
            for i,s in enumerate(blueprint["slides"])]
    prompt=(
        "You are the DATA VISUALIZATION DIRECTOR for an executive-quality "
        "native/editable PowerPoint. For every slide decide whether source "
        "data should be shown as a bar chart, line chart, or no chart. "
        "Choose based on what its actual conclusion requires. Do not repeat "
        "the same series/category encoding on different slides. "
        "Never fabricate a source column, data point or unit. A net "
        "difference chart MUST bind the computed difference series, not "
        "only one contributing input; choose source column names exactly "
        "as given. The difference operation left minus right is calculated "
        "by the runtime. A non-quantitative slide should use visual_type none. "
        "No raw code, API tokens or unauthorized tool calls. "
        "Return JSON ONLY: "
        '{"schema_version":2,"slides":[{"slide_index":0,'
        '"visual_type":"none|bar|line","category_column":null,'
        '"series_columns":[],"difference":null,"claim_binding":null,'
        '"reason":"why this chart conveys a relevant, nonduplicate claim"}]}. '
        "For difference, use "
        '{"operation":"subtract","left_column":"exact field",'
        '"right_column":"exact field","label":"meaningful measure"}. '
        "No private reasoning.\nGoal:\n"+objective[:2600]+
        "\nApproved slide contracts:\n"+
        json.dumps(slides,ensure_ascii=False)[:15500]+
        "\nActual source table:\n"+
        json.dumps({"headers":headers,"sample":rows[:5]},
                   ensure_ascii=False,default=str)[:8000])
    try:
        for attempt in range(2):
            response=await generate_with_recovery(
                client,role="work",model=model,timeout=85,
                contents=prompt+(
                    "\nPrevious chart strategy failed its evidence/duplication "
                    "contract. Correct it with exact source columns." if attempt else ""),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=4200,temperature=.15))
            try:
                return validate_visual_plan(
                    decode_model_json(
                        getattr(response,"text","") or "",max_bytes=26000),
                    blueprint,table)
            except (ValueError,TypeError,KeyError):
                if attempt:
                    raise VisualStrategyError(
                        "No source-grounded and nonduplicate visual plan")
        raise VisualStrategyError("Chart director did not converge")
    finally:
        if owned:
            await client.aio.aclose()


def inspect_chart_bindings(path,plan: dict,table) -> dict:
    """Compare ACTUAL editable chart values to recomputed source data."""
    from pptx import Presentation
    deck=Presentation(path)
    expected=plan["slides"]
    if len(deck.slides)!=len(expected):
        raise VisualStrategyError("Visual plan lost one or more slides")
    charts=0
    for index,item in enumerate(expected):
        objects=[shape.chart for shape in deck.slides[index].shapes
                 if shape.has_chart]
        if item["visual_type"]=="none":
            if objects:
                raise VisualStrategyError("Unapproved chart appeared on text slide")
            continue
        if len(objects)!=1:
            raise VisualStrategyError("Expected one real editable chart per intended slide")
        cat,measure=chart_values(item,table)
        chart=objects[0]
        if len(chart.series)!=len(measure):
            raise VisualStrategyError("Rendered chart omitted an approved series")
        for actual,(label,values) in zip(chart.series,measure.items()):
            if actual.name!=label or len(actual.values)!=len(values):
                raise VisualStrategyError("Chart series does not match source receipt")
            if any(abs(float(a)-float(b))>1e-9
                   for a,b in zip(actual.values,values)):
                raise VisualStrategyError("Chart values differ from original source")
        charts+=1
    return {"passed":True,"chart_count":charts,
            "checks":["approved_chart_binding","no_duplicate_encoding",
                      "independently_recomputed_native_chart_series"]}
