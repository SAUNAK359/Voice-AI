"""Spreadsheet formula and source-metric verification without trusting Excel caches."""
from __future__ import annotations

import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


_FORMULA = re.compile(
    r"=(COUNT|AVERAGE|MIN|MAX)\(Data!([A-Z]{1,3})2:\2([1-9][0-9]*)\)\Z")


def _close(a, b):
    return (isinstance(a, (int, float)) and not isinstance(a, bool)
            and isinstance(b, (int, float)) and not isinstance(b, bool)
            and math.isfinite(a) and math.isfinite(b)
            and math.isclose(a, b, rel_tol=1e-8, abs_tol=2e-5))


def verify_workbook(path: Path, *, dataset_summary: dict | None = None,
                    require_recalculation: bool = False) -> dict:
    from openpyxl import load_workbook
    from openpyxl.utils import column_index_from_string
    from .work_skills import analyze

    wb = load_workbook(path, read_only=True, data_only=False)
    try:
        if "Summary" not in wb.sheetnames:
            raise ValueError("Workbook summary is missing")
        if "Data" not in wb.sheetnames:
            if dataset_summary is not None:
                raise ValueError("Workbook omitted source data")
            return {"status": "no_source_dataset", "formulas": 0,
                    "recalculation": "not_applicable"}
        if "Checks" not in wb.sheetnames:
            raise ValueError("Workbook formula evidence is missing")
        data = wb["Data"]
        values = list(data.iter_rows(values_only=True))
        headers = [str(v or "") for v in values[0]]
        rows = [[("" if v is None else str(v)) for v in record] for record in values[1:]]
        actual = analyze(headers, rows)
        if dataset_summary:
            for key in ("rows","columns","duplicates","missing"):
                if actual[key] != dataset_summary[key]:
                    raise ValueError("Workbook source metrics differ from SQL evidence")
            for field,stats in dataset_summary.get("numeric",{}).items():
                observed = actual["numeric"].get(field)
                if observed is None or stats["count"] != observed["count"] or any(
                    not _close(stats[name], observed[name]) for name in ("mean","min","max")):
                    raise ValueError("Workbook numeric values differ from independent SQL evidence")
        check = list(wb["Checks"].iter_rows(values_only=True))
        if len(check) < 2 or check[0][0] != "Metric":
            raise ValueError("Workbook formula contract malformed")
        if (check[1][0] != "Source rows"
            or check[1][1] != (f"=ROWS(Data!A2:A{len(rows)+1})"
                               if rows else "=COUNTA(Data!A2:A2)")
            or check[1][2] != len(rows)):
            raise ValueError("Workbook row-count formula or expected value tampered")
        formulas = 1
        verified = []
        for row in check[2:]:
            if len(row) < 3:
                raise ValueError("Malformed formula-check row")
            name, formula, expected = row[:3]
            match = _FORMULA.fullmatch(formula or "")
            if not match:
                raise ValueError("Unapproved workbook formula")
            function, col, upper = match.groups()
            index = column_index_from_string(col) - 1
            if index >= len(headers) or int(upper) != max(2,len(rows)+1):
                raise ValueError("Workbook formula references wrong source range")
            numbers = []
            for record in values[1:]:
                value = record[index]
                if value is not None and value != "":
                    if not isinstance(value,(int,float)) or isinstance(value,bool):
                        raise ValueError("Formula field contains nonnumeric values")
                    numbers.append(float(value))
            if not numbers:
                raise ValueError("Formula operates on an empty numeric field")
            measured = {
                "COUNT":lambda:len(numbers),
                "AVERAGE":lambda:sum(numbers)/len(numbers),
                "MIN":lambda:min(numbers),
                "MAX":lambda:max(numbers),
            }[function]()
            if not _close(measured,expected):
                raise ValueError("Independent calculation conflicts with expected formula")
            verified.append((measured, expected))
            formulas += 1
        if any(cell.data_type == "f" for ws in wb.worksheets if ws.title!="Checks"
               for row in ws.iter_rows() for cell in row):
            raise ValueError("Unexpected executable spreadsheet formula outside Checks")
    finally:
        wb.close()
    report = {"status":"independently_verified","formulas":formulas,
              "recalculation":"not_executed"}
    if require_recalculation:
        binary = shutil.which("libreoffice") or shutil.which("soffice")
        if not binary:
            raise RuntimeError("Strict artifact QA requires LibreOffice Calc")
        with tempfile.TemporaryDirectory(prefix="rizzler-calc-") as temp:
            root = Path(temp)
            out = root/"out"
            out.mkdir()
            profile = (root/"profile").as_uri()
            try:
                process = subprocess.run(
                    [binary, "--headless", "-env:UserInstallation="+profile,
                     "--convert-to", "xlsx", "--outdir", str(out), str(path)],
                    capture_output=True, timeout=60, check=False)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Spreadsheet recalculation exceeded time budget") from exc
            target = out/path.name
            if process.returncode or not target.is_file():
                raise RuntimeError("Independent spreadsheet recalculation failed")
            recalc = load_workbook(target, read_only=True, data_only=True)
            try:
                computed = list(recalc["Checks"].iter_rows(
                    min_row=2, min_col=2, max_col=2, values_only=True))
                reference = [len(rows)] + [v[0] for v in verified]
                if len(computed) != len(reference) or any(
                    not _close(row[0], expected) for row,expected in zip(computed,reference)):
                    raise ValueError("Recalculated formula values differ from independent arithmetic")
            finally:
                recalc.close()
        report["recalculation"] = "libreoffice_independently_reconciled"
    return report
