#!/usr/bin/env python3
"""Frozen tool-routing confusion matrix; offline contract evidence, not live quality."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
from rizzler.voice_tools import classify_tool

ACTIONS = ("direct","web_search","math","work_submit","work_status","work_cancel")


def evaluate(path: Path) -> dict:
    confusion=Counter()
    examples=[]
    with Path(path).open(encoding="utf-8") as file:
        for num,line in enumerate(file,1):
            record=json.loads(line)
            if (not isinstance(record,dict) or set(record)!={"text","expected"}
                    or not isinstance(record["text"],str)
                    or record["expected"] not in ACTIONS):
                raise ValueError(f"Invalid routing fixture line {num}")
            actual=classify_tool(record["text"],True) or "direct"
            confusion[(record["expected"],actual)]+=1
            if actual!=record["expected"] and len(examples)<16:
                examples.append({"line":num,"expected":record["expected"],"observed":actual})
    n=sum(confusion.values())
    if n==0:raise ValueError("No routing fixtures")
    per_class={}
    for name in ACTIONS:
        tp=confusion[(name,name)]
        target=sum(c for (label,_),c in confusion.items() if label==name)
        predicted=sum(c for (_,label),c in confusion.items() if label==name)
        per_class[name]={
            "support":target,"precision":round(tp/predicted,4) if predicted else None,
            "recall":round(tp/target,4) if target else None}
    unsafe=sum(c for (label,pred),c in confusion.items()
               if pred in ("work_submit","work_cancel") and label!=pred)
    return {"schema_version":1,"fixture_count":n,"correct":sum(confusion[(x,x)] for x in ACTIONS),
            "accuracy":round(sum(confusion[(x,x)] for x in ACTIONS)/n,4),
            "unauthorized_side_effect_routes":unsafe,
            "per_class":per_class,
            "errors":examples,
            "limitations":"Hand-curated frozen routing examples; not production recall or a real-model benchmark"}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--fixtures",type=Path,default=Path("benchmarks/fixtures/tool_routing_v11.jsonl"))
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    report=evaluate(args.fixtures)
    serialized=json.dumps(report,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(serialized+"\n",encoding="utf-8")
    print(serialized)
    if report["errors"] or report["unauthorized_side_effect_routes"]:
        raise SystemExit("Routing acceptance fixture failed")


if __name__=="__main__":
    main()
