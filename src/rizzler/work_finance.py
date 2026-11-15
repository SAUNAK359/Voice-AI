"""Reproducible grouped financial analytics for explicitly typed source columns.

This module performs arithmetic, not intent routing. It never infers currencies,
units, or data semantics from the objective. It recognizes only matching source
column names and declines to compute unsupported financial metrics.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re


def financial_profile(headers: list[str], rows: list[list[str]]) -> dict | None:
    """Exact, source-grounded aggregates, no synthetic facts and no floating drift."""
    names = {re.sub(r"\W+", "_", name.strip().lower()).strip("_"): i
             for i, name in enumerate(headers)}
    def choose(*values):
        return next((names[v] for v in values if v in names), None)
    revenue = choose("revenue_inr", "total_revenue_inr", "sales_inr",
                     "revenue_usd", "total_revenue_usd", "sales_usd")
    cost = choose("cost_inr", "total_cost_inr", "cost_usd", "total_cost_usd")
    group = choose("region", "area", "territory", "geography")
    product = choose("product", "product_category", "category", "segment")
    units = choose("units", "units_sold", "quantity")
    if revenue is None or cost is None:
        return None
    money_unit = headers[revenue].split("_")[-1].upper()
    if money_unit not in ("INR", "USD") or headers[cost].split("_")[-1].upper() != money_unit:
        return None
    profit = choose("gross_profit_"+money_unit.lower(), "profit_"+money_unit.lower())
    if group is None and product is None:
        return None
    totals = defaultdict(lambda: [Decimal(0),Decimal(0),Decimal(0),Decimal(0)])
    breakdowns = {headers[index]: defaultdict(lambda: [Decimal(0),Decimal(0),Decimal(0),Decimal(0)])
                  for index in (group,product) if index is not None}
    source_profit_checked = 0
    for row in rows:
        try:
            rev, cst = Decimal(str(row[revenue])), Decimal(str(row[cost]))
            qty = Decimal(str(row[units])) if units is not None and str(row[units]).strip() else Decimal(0)
            if not all(v.is_finite() for v in (rev,cst,qty)):
                raise ValueError("Nonfinite finance data")
        except (InvalidOperation, IndexError, ValueError) as exc:
            raise ValueError("Finance column contains invalid data") from exc
        gp = rev-cst
        if profit is not None:
            try:
                claimed = Decimal(str(row[profit]))
            except (InvalidOperation, IndexError) as exc:
                raise ValueError("Gross profit data malformed") from exc
            if gp != claimed:
                raise ValueError("Source gross profit does not reconcile with revenue minus cost")
            source_profit_checked += 1
        for target in (totals["all"],*(buckets[str(row[headers.index(name)]) or "Unspecified"]
                     for name,buckets in breakdowns.items())):
            for i,value in enumerate((rev,cst,gp,qty)):
                target[i]+=value
    def canonical(values):
        r,c,p,u=values
        return {"revenue":float(r),"cost":float(c),"gross_profit":float(p),
                "gross_margin_pct":round(float(p/r*100),4) if r else None,
                "units":float(u) if units is not None else None}
    return {"currency":money_unit, "total":canonical(totals["all"]),
            "groups":{k:{g:canonical(val) for g,val in sorted(b.items())}
                      for k,b in breakdowns.items()},
            "source_profit_rows_verified":source_profit_checked,
            "rows":len(rows), "calculation":"decimal_exact"}
