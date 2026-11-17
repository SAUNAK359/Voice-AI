"""Source-bounded model-directed tabular extraction for Work artifacts.

The reasoning model decides what columns and rows are useful. Every row must
point to a directly fetched source and a verbatim excerpt, and quantitative
cells must appear as whole tokens in the excerpt. This is conservative
extraction verification, not proof that the source is independently true.
"""
from __future__ import annotations

import json
import re
from .research_evidence import safe_source_url

TABLE_SCHEMA={
    "type":"object",
    "properties":{
        "columns":{"type":"array","items":{"type":"string"}},
        "rows":{"type":"array","items":{
            "type":"object",
            "properties":{
                "cells":{"type":"array","items":{"type":"string"}},
                "source_url":{"type":"string"},
                "quote":{"type":"string"},
            },
            "required":["cells","source_url","quote"],
            "additionalProperties":False,
        }},
    },
    "required":["columns","rows"],
    "additionalProperties":False,
}
_NUMBER=re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")


def validate(table: dict, passages: list[dict]) -> dict:
    if type(table) is not dict or set(table)!={"columns","rows"}:
        raise ValueError("Invalid extracted table contract")
    columns=table["columns"]; records=table["rows"]
    if (type(columns) is not list or not 1<=len(columns)<=24 or
            any(type(x) is not str or not 1<=len(x.strip())<=90
                for x in columns) or len(set(columns))!=len(columns)):
        raise ValueError("Invalid extracted table columns")
    if type(records) is not list or not 1<=len(records)<=150:
        raise ValueError("Extracted table has no bounded rows")
    accepted={x["url"]:x["excerpt"] for x in passages
              if type(x) is dict and type(x.get("url")) is str
              and type(x.get("excerpt")) is str}
    if not accepted:
        raise ValueError("Tabular extraction requires fetched source excerpts")
    validated=[]
    for row in records:
        if type(row) is not dict or set(row)!={"cells","source_url","quote"}:
            raise ValueError("Invalid extracted observation")
        cells=row["cells"]; url=row["source_url"]; quote=row["quote"]
        if (type(cells) is not list or len(cells)!=len(columns) or
                any(type(c) is not str or len(c)>150 for c in cells)):
            raise ValueError("Data row shape differs from extracted columns")
        if (url not in accepted or safe_source_url(url)!=url
                or type(quote) is not str or not 10<=len(quote)<=900
                or quote not in accepted[url]):
            raise ValueError("Row has no directly retrievable source passage")
        for cell in cells:
            raw=cell.strip()
            if _NUMBER.fullmatch(raw):
                if not re.search(
                    r"(?<![\w.])"+re.escape(raw)+r"(?![\w.])",
                    quote):
                    raise ValueError("Numerical cell lacks verbatim source evidence")
        validated.append({"cells":cells,"source_url":url,"quote":quote})
    return {"columns":columns,"rows":validated}


def as_table(value: dict) -> tuple[list[str],list[list[str]]]:
    columns=value["columns"]+["Source URL"]
    return columns,[record["cells"]+[record["source_url"]]
                    for record in value["rows"]]


async def extract(objective: str, passages: list[dict]) -> dict | None:
    if not passages:
        return None
    from .work_sglang import enabled as local_enabled, decision
    if not local_enabled():
        # Do not silently buy a second provider or claim unsupported verification.
        return None
    from .production_guard import reserve_provider_call
    reserve_provider_call("work")
    bounded=[{"url":p["url"],"excerpt":p["excerpt"][:2500]}
             for p in passages[:12] if isinstance(p,dict)
             and isinstance(p.get("excerpt"),str) and isinstance(p.get("url"),str)]
    if not bounded:
        return None
    prompt=(
        "You are an evidence-constrained data engineer. Decide whether the "
        "user task requires a useful, actual table. Extract a typed-looking "
        "column/row dataset only from the verbatim fetched passages. "
        "Choose columns dynamically. Every row needs one exact source URL "
        "and an EXACT contiguous quote from that source. Numerical cell values "
        "must appear literally inside that quote. Do not infer, interpolate, "
        "convert, extrapolate, or invent market OHLCV values. Distinguish "
        "reported dates and market closures. When no reliable tabular rows "
        "exist, return empty columns and rows. User objective: "+
        json.dumps(objective[:5000])+"\nDirect source passages:\n"+
        json.dumps(bounded,ensure_ascii=False)[:33000])
    response=await decision(prompt,TABLE_SCHEMA,max_tokens=7500,
                            temperature=0.1)
    if response.get("columns")==[] and response.get("rows")==[]:
        return None
    return validate(response,bounded)
