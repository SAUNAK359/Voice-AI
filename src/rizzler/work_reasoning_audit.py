"""V26 quantitative reasoning oracle: model selects, Python computes/proves.

The model selects analysis dimensions and requested assertions; it NEVER
decides arithmetic truth. Values derive only from the independently uploaded
table, with exact row reconciliation and an opaque content digest. Observational
data cannot by itself authorize a causal conclusion.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json

from .cognitive_json import decode_model_json

ASSERTIONS=frozenset({
    "all_differences_negative","all_differences_positive",
    "uniform_differences","net_total_equals",
    "series_a_greater_than_b_total","monotonic_difference",
    "causal_effect_identified"})
AGGREGATIONS=frozenset({"sum","mean"})


class MethodologyError(ValueError):
    """An analytical plan lacks data, dimensionality or verifiable support."""


def numeric(value):
    if isinstance(value,bool) or value is None:
        raise MethodologyError("Missing or invalid numeric datum")
    try:
        result=Decimal(str(value).strip())
    except (InvalidOperation,ValueError) as exc:
        raise MethodologyError("Non-numeric source value") from exc
    if not result.is_finite():
        raise MethodologyError("Non-finite source value")
    return result


def validate_comparison_plan(plan: dict, table) -> dict:
    if (not isinstance(plan,dict) or set(plan)!={
            "schema_version","category_column","first_measure",
            "second_measure","aggregation","measurement_unit",
            "analytical_question","confounder_columns"}
            or plan["schema_version"]!=2):
        raise MethodologyError("Unapproved analytical comparison schema")
    headers,rows=table
    if (not isinstance(headers,(tuple,list)) or
            len(headers)!=len(set(headers))
            or not isinstance(rows,(tuple,list)) or not rows
            or len(rows)>100000):
        raise MethodologyError("No suitable auditable data rows")
    category,first,second=(plan[k] for k in (
        "category_column","first_measure","second_measure"))
    if any(type(s) is not str or s not in headers for s in (
            category,first,second)) or len({category,first,second})!=3:
        raise MethodologyError("Analytical dimensions do not match source schema")
    if plan["aggregation"] not in AGGREGATIONS:
        raise MethodologyError("Unsupported aggregation method")
    if (not isinstance(plan["measurement_unit"],str)
            or not 2<=len(plan["measurement_unit"])<=120
            or not isinstance(plan["analytical_question"],str)
            or not 15<=len(plan["analytical_question"])<=500):
        raise MethodologyError("Missing analytical purpose or unit disclosure")
    conf=plan["confounder_columns"]
    if (not isinstance(conf,list) or len(conf)>8
            or len(set(conf))!=len(conf)
            or any(type(s) is not str or s not in headers
                   or s in (first,second,category) for s in conf)):
        raise MethodologyError("Confounder reference is unavailable")
    cols={name:headers.index(name) for name in (first,second)}
    for row in rows:
        if len(row)!=len(headers):
            raise MethodologyError("Source row length mismatch")
        for index in cols.values():
            numeric(row[index])
    return plan


def execute_comparison(plan: dict,table) -> dict:
    validate_comparison_plan(plan,table)
    headers,rows=table
    idx={key:headers.index(plan[key]) for key in (
        "category_column","first_measure","second_measure")}
    grouped=defaultdict(list)
    source_rows=[]
    for index,row in enumerate(rows):
        label=str(row[idx["category_column"]])
        a=numeric(row[idx["first_measure"]])
        b=numeric(row[idx["second_measure"]])
        grouped[label].append((a,b))
        source_rows.append({
            "row":index,"group":label,
            "first":str(a),"second":str(b),
            "difference":str(b-a)})
    outputs=[]
    for label,values in grouped.items():
        count=Decimal(len(values))
        a=sum((pair[0] for pair in values),Decimal(0))
        b=sum((pair[1] for pair in values),Decimal(0))
        if plan["aggregation"]=="mean":
            a/=count
            b/=count
        outputs.append({
            "category":label,"count":len(values),
            "first":str(a),"second":str(b),
            "difference":str(b-a)})
    # Values are source-computed, not LLM synthesized.
    differences=[numeric(row["difference"]) for row in outputs]
    total_first=sum((numeric(r["first"]) for r in source_rows),Decimal(0))
    total_second=sum((numeric(r["second"]) for r in source_rows),Decimal(0))
    overlaps={}
    for name in plan["confounder_columns"]:
        i=headers.index(name)
        by_cat=defaultdict(set)
        for row in rows:
            by_cat[str(row[idx["category_column"]])].add(str(row[i]))
        overlapping=(bool(by_cat) and len(set.intersection(*by_cat.values()))>0)
        overlaps[name]={"observed_overlap_across_category":overlapping,
                        "causal_inference_supported":False}
    source_digest=hashlib.sha256(json.dumps(
        {"headers":list(headers),"rows":[list(r) for r in rows]},
        ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    result={
        "schema_version":2,"source_sha256":source_digest,
        "category_column":plan["category_column"],
        "first_measure":plan["first_measure"],
        "second_measure":plan["second_measure"],
        "aggregation":plan["aggregation"],
        "measurement_unit":plan["measurement_unit"],
        "groups":outputs,
        "total_first":str(total_first),"total_second":str(total_second),
        "total_difference":str(total_second-total_first),
        "all_differences_negative":all(x<0 for x in differences),
        "all_differences_positive":all(x>0 for x in differences),
        "uniform_differences":len(set(differences))<=1,
        "monotonic_difference":(
            all(a<=b for a,b in zip(differences,differences[1:])) or
            all(a>=b for a,b in zip(differences,differences[1:]))),
        "confounder_diagnostics":overlaps,
        "epistemic_limitations":[
            "These are descriptive computations, not proof of causation.",
            "Units and population must be confirmed against the original source.",
            "Analyses with sparse or confounded observations cannot establish "
            "a defensible causal or seasonal effect."
        ],
    }
    return result


def verify_assertion(receipt: dict, *,predicate: str,
                     asserted_value=None) -> dict:
    """A normalized claim is checked against computation, never model prose."""
    if predicate not in ASSERTIONS:
        raise MethodologyError("Unsupported claim or causal predicate")
    if receipt.get("schema_version")!=2:
        raise MethodologyError("No accepted analysis receipt")
    if predicate=="causal_effect_identified":
        # Causal identification requires a separate approved study design;
        # source observations alone are never sufficient.
        verified=False
    elif predicate=="net_total_equals":
        if asserted_value is None:
            raise MethodologyError("Numerical assertion lacks a target")
        verified=numeric(receipt["total_difference"])==numeric(asserted_value)
    elif predicate=="series_a_greater_than_b_total":
        verified=numeric(receipt["total_first"])>numeric(receipt["total_second"])
    else:
        verified=receipt[predicate] is True
    return {"predicate":predicate,"supported":verified,
            "source_sha256":receipt["source_sha256"],
            "reason":"computed_source_receipt" if verified
                     else "unsupported_by_observed_data"}


async def choose_comparison_plan(objective: str,table, *,
                                 model: str,api_key: str,client=None) -> dict:
    """LLM maps a real task to columns; no static keyword-based router."""
    if not api_key:
        raise MethodologyError("No authorized analytical planning model")
    owned=client is None
    if owned:
        from google import genai
        client=genai.Client(api_key=api_key)
    from google.genai import types
    from .cognitive_provider import generate_with_recovery
    headers,rows=table
    # Bounded examples establish shape without exposing full confidential files.
    preview=[dict(zip(headers,row)) for row in rows[:4]]
    prompt=(
        "You are the analytical-method specialist. Determine whether this "
        "user's request calls for a defensible TWO-measure comparison. "
        "Choose exact uploaded column names; never invent a column or unit. "
        "The method may calculate arithmetic differences (second minus first), "
        "source groups and potential confounding dimensions. An aggregation "
        "is sum only for additive measures; otherwise mean. Missing currency "
        "or units MUST be represented as 'unspecified_by_source'. "
        "This is descriptive evidence, not causal proof. You do not have "
        "permission to execute SQL, external network requests or code. "
        "Return JSON ONLY: "
        '{"schema_version":2,"category_column":"existing category",'
        '"first_measure":"existing numeric column",'
        '"second_measure":"existing numeric column",'
        '"aggregation":"sum|mean",'
        '"measurement_unit":"unit or unspecified_by_source",'
        '"analytical_question":"specific relevant comparison",'
        '"confounder_columns":["existing category column"]}. '
        "No private reasoning.\nOriginal user request:\n"+
        objective[:2800]+"\nApproved source schema:\n"+
        json.dumps({"headers":headers,"sample":preview},default=str)[:8500])
    try:
        failure=""
        for attempt in range(2):
            response=await generate_with_recovery(
                client,role="work",model=model,timeout=85,
                contents=prompt+failure,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=1500,temperature=.12))
            try:
                return validate_comparison_plan(
                    decode_model_json(
                        getattr(response,"text","") or "",max_bytes=10000),
                    table)
            except (ValueError,TypeError,KeyError):
                failure=(
                    "\nInvalid original source schema or measurement. "
                    "Do not invent fields, source units or unsupported tests.")
        raise MethodologyError("Model failed to plan a source-valid comparison")
    finally:
        if owned:
            await client.aio.aclose()
