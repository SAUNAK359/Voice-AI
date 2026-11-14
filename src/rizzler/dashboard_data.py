"""Bounded, owner-authorized tabular data for interactive artifact dashboards.

The server supplies verified source cells only; chart decisions and exploratory
navigation happen in the client or through the Gemini preview tool.
"""
from __future__ import annotations
import csv
from pathlib import Path

MAX_ROWS=10000
MAX_COLS=50

def data(path:Path,kind:str,sheet:str|None=None):
    path=Path(path)
    if kind=="csv":
        with path.open(encoding="utf-8-sig",newline="") as source:
            reader=csv.reader(source)
            headers=next(reader,None)
            if not headers or len(headers)>MAX_COLS:raise ValueError("Invalid CSV header")
            rows=[]
            for index,row in enumerate(reader):
                if index>=MAX_ROWS:raise ValueError("Dashboard exceeds 10,000-row interactive cap")
                if len(row)!=len(headers):raise ValueError("Inconsistent CSV row")
                rows.append([v[:1000] for v in row])
        return {"kind":"csv","sheet":None,"sheets":[],"columns":headers,"rows":rows,
                "truncated":False,"source_rows":len(rows)}
    if kind!="xlsx":raise ValueError("Not an interactive table")
    from openpyxl import load_workbook
    book=load_workbook(path,read_only=True,data_only=True)
    try:
        names=book.sheetnames
        if not names:raise ValueError("Workbook contains no sheets")
        if sheet is not None and sheet not in names:raise ValueError("Unknown worksheet")
        chosen=sheet or ("Data" if "Data" in names else names[0])
        ws=book[chosen]
        iterator=ws.iter_rows(values_only=True)
        headers=next(iterator,None)
        if not headers:raise ValueError("Empty worksheet")
        if len(headers)>MAX_COLS:raise ValueError("Workbook exceeds dashboard column cap")
        rows=[]
        for i,row in enumerate(iterator):
            if i>=MAX_ROWS:raise ValueError("Workbook exceeds dashboard row cap")
            rows.append([str(v)[:1000] if v is not None else "" for v in row[:len(headers)]])
        return {"kind":"xlsx","sheet":chosen,"sheets":names[:100],
                "columns":[str(v)[:150] if v is not None else "Column "+str(i+1)
                           for i,v in enumerate(headers)],
                "rows":rows,"truncated":False,"source_rows":len(rows)}
    finally:book.close()
