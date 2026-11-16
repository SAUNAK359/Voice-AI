"""Strict Gemini Live tool-call contracts, shared by tool declaration and execution.

The model decides when to use tools. The backend ensures function-call arguments
match its declared capability and bounds before touching private Work state.
"""
from __future__ import annotations
import re
from .contracts import DELIVERABLES

DECLARATIONS=[
            {"name":"work_list","description":"List my owned queued, active and completed projects.","parameters":{"type":"OBJECT","properties":{}}},
            {"name":"work_status","description":"Get the actual saved status and verified artifacts of my project.","parameters":{"type":"OBJECT","properties":{"job_id":{"type":"STRING"}},"required":["job_id"]}},
            {"name":"work_submit","description":"Queue substantial autonomous work for the Work Engine; respond immediately with a job receipt. Construct a complete objective, success criteria and expected output formats.","parameters":{"type":"OBJECT","properties":{"objective":{"type":"STRING"},"deliverables":{"type":"ARRAY","items":{"type":"STRING"}},"source_coverage":{"type":"STRING","enum":["targeted","complete"]},"evidence_scope":{"type":"STRING","enum":["auto","uploaded_only","external_allowed"]}},"required":["objective","deliverables","source_coverage"]}},
            {"name":"source_search","description":"Retrieve grounded excerpts from my selected indexed attachments, with source and passage references.","parameters":{"type":"OBJECT","properties":{"query":{"type":"STRING"}},"required":["query"]}},
            {"name":"preview_open","description":"Open an owned completed job artifact in the visual preview panel.","parameters":{"type":"OBJECT","properties":{"job_id":{"type":"STRING"}},"required":["job_id"]}},
            {"name":"preview_slide","description":"Navigate the user's visual preview to a specific slide number in an owned completed presentation.","parameters":{"type":"OBJECT","properties":{"job_id":{"type":"STRING"},"slide":{"type":"INTEGER"}},"required":["job_id","slide"]}},
            {"name":"preview_highlight","description":"Highlight exact text in the user's completed visual artifact.","parameters":{"type":"OBJECT","properties":{"job_id":{"type":"STRING"},"text":{"type":"STRING"}},"required":["job_id","text"]}},
            {"name":"preview_dashboard","description":"Interactively configure a real dashboard made from the user's completed data artifact. Choose its chart, grouping, numeric metric and optional filter from the actual available columns rather than guessing values.","parameters":{"type":"OBJECT","properties":{"job_id":{"type":"STRING"},"group_by":{"type":"STRING"},"metric":{"type":"STRING"},"chart":{"type":"STRING"},"filter_column":{"type":"STRING"},"filter_value":{"type":"STRING"}},"required":["job_id","group_by","metric","chart","filter_column","filter_value"]}},
        ]

_ID = re.compile(r"[a-f0-9]{32}\Z")
_LIMITS = {
    "work_list": {},
    "work_status": {"job_id": (32, 32)},
    "work_submit": {"objective": (3, 5000)},
    "source_search": {"query": (1, 2000)},
    "preview_open": {"job_id": (32, 32)},
    "preview_slide": {"job_id": (32, 32)},
    "preview_highlight": {"job_id": (32, 32), "text": (1, 160)},
    "preview_dashboard": {
        "job_id": (32, 32), "group_by": (1, 160),
        "metric": (1, 160), "chart": (3, 15),
        "filter_column": (0, 160), "filter_value": (0, 120),
    },
}
_BY_NAME={item["name"]:item["parameters"] for item in DECLARATIONS}
assert set(_BY_NAME)==set(_LIMITS)==set(x["name"] for x in DECLARATIONS)

def validate_call(name: str, args, *, enabled: bool=True) -> dict:
    if not enabled or type(name) is not str or name not in _BY_NAME:
        raise ValueError("Tool is not authorized")
    schema=_BY_NAME[name]
    if type(args) is not dict:
        raise ValueError("Tool arguments must be an object")
    properties=schema.get("properties",{})
    if not set(schema.get("required",[])).issubset(args) or not set(args).issubset(properties):
        raise ValueError("Missing or unknown tool arguments")
    if name=="work_list" and args:
        raise ValueError("List tool accepts no arguments")
    for key,value in args.items():
        spec=properties[key]
        expected=spec["type"]
        if expected=="STRING":
            if type(value) is not str or (
                key in _LIMITS[name] and not (
                    len(value)<=_LIMITS[name][key][1] and
                    len(value.strip())>=_LIMITS[name][key][0])):
                raise ValueError("Invalid tool string")
            if key=="job_id" and not _ID.fullmatch(value):
                raise ValueError("Invalid Work job ID")
            if "enum" in spec and value not in spec["enum"]:
                raise ValueError("Unsupported enum value")
            if name=="preview_dashboard" and key=="chart" and value not in ("bar","line","scatter"):
                raise ValueError("Unsupported chart type")
        elif expected=="INTEGER":
            if type(value) is not int or not (1<=value<=500):
                raise ValueError("Invalid slide index")
        elif expected=="ARRAY":
            from .contracts import DELIVERABLES
            if (type(value) is not list or not 1<=len(value)<=12 or
                len(set(map(repr,value)))!=len(value) or
                any(type(v) is not str or v not in DELIVERABLES for v in value)):
                raise ValueError("Invalid deliverable array")
        else:
            raise ValueError("Unsupported tool argument schema")
    return args

def public_schema(name: str):
    """JSON Schema mirror used by offline test matrix and auditing."""
    if name not in _BY_NAME:raise ValueError("Unregistered tool")
    prop={}
    source=_BY_NAME[name]
    for key,spec in source.get("properties",{}).items():
        field={"type":{"STRING":"string","INTEGER":"integer","ARRAY":"array"}[spec["type"]]}
        if key in _LIMITS[name]:
            low,high=_LIMITS[name][key]
            field["minLength"]=low
            field["maxLength"]=high
            if low>0 and field["type"]=="string":
                field["pattern"]=(r"\S" if low==1 else r"\S[\s\S]{"+str(low-2)+r",}\S")
        if key=="job_id":field["pattern"]="^[a-f0-9]{32}$"
        if key=="slide":
            field["minimum"]=1
            field["maximum"]=500
        if "enum" in spec:field["enum"]=list(spec["enum"])
        if name=="preview_dashboard" and key=="chart":field["enum"]=["bar","line","scatter"]
        if key=="deliverables":
            field.update({"items":{"type":"string","enum":sorted(DELIVERABLES)},
                          "minItems":1,"maxItems":12,"uniqueItems":True})
        prop[key]=field
    return {"type":"object","properties":prop,
            "required":list(source.get("required",[])),
            "additionalProperties":False}
