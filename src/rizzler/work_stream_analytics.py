"""Secure, source-hashed, disk-backed CSV/XLSX analytics for V26.

The database is temporary, private and never published. Full-source metrics
are computed from streamed rows; bounded SQL results can be shared with the
model but raw source rows and private SQLite files cannot.
"""
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from .work_large_uploads import HARD_LIMIT, sha256_file
from .work_sql_exploration import SQLResearchSandbox

MAX_ROWS = 5_000_000
MAX_COLUMNS = 50
MAX_CELL_CHARS = 32_768
MAX_DISK_BYTES = 1_400_000_000
MAX_TRACKED_DISTINCT = 4096
BATCH_SIZE = 512


def _rows_from_source(path: Path):
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.reader(stream, strict=True):
                yield row
    elif path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            ws = workbook.active
            if ws.max_column > MAX_COLUMNS:
                raise ValueError("Dataset exceeds column budget")
            for row in ws.iter_rows(values_only=True):
                yield ["" if value is None else str(value) for value in row]
        finally:
            workbook.close()
    else:
        raise ValueError("Only validated CSV/XLSX datasets are supported")


def _number(value: str):
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite():
        raise ValueError("Non-finite numeric source value")
    if len(value) > 55 or number.adjusted() > 22 or number.adjusted() < -16:
        raise ValueError("Numeric precision/exponent outside verified range")
    return number


class StreamingSQLDataset(SQLResearchSandbox):
    """Full-file SQL sandbox with bounded ingestion, memory and disk."""

    def __init__(self, source: str | Path):
        raw_source = Path(source)
        if raw_source.is_symlink():
            raise ValueError("Symlink sources are not accepted")
        self.source = raw_source.resolve(strict=True)
        if not self.source.is_file():
            raise ValueError("Invalid source path")
        self.source_bytes = self.source.stat().st_size
        if not 10 <= self.source_bytes <= HARD_LIMIT:
            raise ValueError("Dataset size exceeds V26 policy")
        self.source_sha256 = sha256_file(self.source)
        self.temp = TemporaryDirectory(prefix="rizzler-v26-sql-")
        self.db_path = Path(self.temp.name) / "private_source.sqlite3"
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.calls = 0
        self.closed = False
        try:
            self.db.execute("PRAGMA cache_size=-8192")
            self.db.execute("PRAGMA temp_store=FILE")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self._ingest()
            self.db.set_authorizer(self._authorize)
        except BaseException:
            self.close()
            raise

    def _ingest(self):
        reader = iter(_rows_from_source(self.source))
        header = next(reader, None)
        if (not header or len(header) > MAX_COLUMNS or
                any(not isinstance(h, str) or not h.strip() or len(h) > 200 for h in header) or
                len(set(header)) != len(header)):
            raise ValueError("Source headers are missing, repeated or unsupported")
        self.header = header
        ncols = len(header)
        self.db.execute("CREATE TABLE dataset(row_number INTEGER PRIMARY KEY," +
                        ",".join(f"c{i} TEXT" for i in range(ncols)) + ")")
        self.db.execute("CREATE TABLE row_fingerprints(digest BLOB PRIMARY KEY)")
        insert = "INSERT INTO dataset VALUES (" + ",".join("?" for _ in range(ncols + 1)) + ")"
        numeric = [True] * ncols
        seen_numeric = [False] * ncols
        counts = [0] * ncols
        missing = [0] * ncols
        sums = [Decimal(0) for _ in header]
        minima = [None for _ in header]
        maxima = [None for _ in header]
        distinct = [set() for _ in header]
        distinct_truncated = [False] * ncols
        duplicates = 0
        count = 0
        batch = []
        fingerprints = self.db.cursor()
        with localcontext() as ctx:
            ctx.prec = 80
            for values in reader:
                count += 1
                if count > MAX_ROWS:
                    raise ValueError("Source row count exceeds bounded policy")
                if len(values) != ncols:
                    raise ValueError("Source has inconsistent row widths")
                if any(not isinstance(v, str) or len(v) > MAX_CELL_CHARS for v in values):
                    raise ValueError("Source cell exceeds verified budget")
                digest = hashlib.sha256(json.dumps(
                    values, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")).digest()
                fingerprints.execute("INSERT OR IGNORE INTO row_fingerprints VALUES (?)", (digest,))
                duplicates += int(fingerprints.rowcount == 0)
                for i, raw in enumerate(values):
                    value = raw.strip()
                    if not value:
                        missing[i] += 1
                        continue
                    counts[i] += 1
                    if not distinct_truncated[i]:
                        token = hashlib.blake2b(value.encode("utf-8"), digest_size=16).digest()
                        if len(distinct[i]) >= MAX_TRACKED_DISTINCT and token not in distinct[i]:
                            distinct_truncated[i] = True
                            distinct[i].clear()
                        else:
                            distinct[i].add(token)
                    if numeric[i]:
                        parsed = _number(value)
                        if parsed is None:
                            numeric[i] = False
                        else:
                            seen_numeric[i] = True
                            sums[i] += parsed
                            minima[i] = parsed if minima[i] is None else min(minima[i], parsed)
                            maxima[i] = parsed if maxima[i] is None else max(maxima[i], parsed)
                batch.append((count, *values))
                if len(batch) == BATCH_SIZE:
                    self.db.executemany(insert, batch)
                    batch.clear()
                    if count % (BATCH_SIZE * 20) == 0:
                        self.db.commit()
                        if self.db_path.stat().st_size > MAX_DISK_BYTES:
                            raise ValueError("Temporary SQL storage budget exceeded")
            if batch:
                self.db.executemany(insert, batch)
        self.db.commit()
        if self.db_path.stat().st_size > MAX_DISK_BYTES:
            raise ValueError("Temporary SQL storage budget exceeded")
        if sha256_file(self.source) != self.source_sha256 or self.source.stat().st_size != self.source_bytes:
            raise ValueError("Source changed during incremental analysis")
        if self.db.execute("SELECT COUNT(*) FROM dataset").fetchone()[0] != count:
            raise ValueError("Ingested SQL rows do not reconcile with source")
        fields = []
        metrics = {}
        exact = {}
        for i, name in enumerate(header):
            info = {"name": name, "alias": f"c{i}", "count": counts[i],
                    "missing": missing[i], "type_hint": "numeric" if numeric[i] and seen_numeric[i] else "categorical_or_text",
                    "distinct": ">=4096" if distinct_truncated[i] else len(distinct[i]),
                    "distinct_is_exact": False,
                    "distinct_method": "bounded 128-bit fingerprint (collisions not excluded)"}
            if numeric[i] and seen_numeric[i]:
                with localcontext() as ctx:
                    ctx.prec = 80
                    mean = sums[i] / Decimal(counts[i])
                stats = {"count": counts[i], "min": float(minima[i]),
                         "max": float(maxima[i]), "mean": round(float(mean), 6)}
                metrics[name] = stats
                exact[name] = {"sum": str(sums[i]), "mean": str(mean),
                               "count": counts[i], "source_column": f"c{i}"}
                info["distribution"] = {"min": stats["min"], "max": stats["max"],
                                        "mean": stats["mean"], "quantiles_computed": False}
            fields.append(info)
        self.summary = {
            "rows": count, "columns": ncols, "duplicates": duplicates,
            "duplicate_method": "SHA-256 row fingerprints, collisions not independently excluded",
            "missing": dict(zip(header, missing)), "numeric": metrics,
            "numeric_exact": exact, "sql_row_count": count,
            "sql_numeric_columns_verified": 0,
            "source_sha256": self.source_sha256, "source_bytes": self.source_bytes,
            "source_coverage": "full_uploaded_dataset", "streaming": True,
            "limitations": ["No units or causality inferred from column labels",
                            "Uncached XLSX formulas may appear missing",
                            "Distinct counts are bounded fingerprints, not exact proofs",
                            "One-pass quantiles and variance are not computed"]}
        self.profile = {"row_count": count, "column_count": ncols,
                        "duplicates": duplicates, "fields": fields,
                        "source_sha256": self.source_sha256,
                        "privacy_note": "Only schema, aggregates and authorized SQL results can reach the model."}

    def query(self, query: str) -> dict:
        """Only bounded aggregate-oriented SELECT queries may leave the index."""
        if (not isinstance(query, str) or
                re.search(r"\bWITH\s+RECURSIVE\b", query, re.I) or
                re.search(r"\bSELECT\s+\*", query, re.I) or
                not re.search(r"\b(COUNT|SUM|AVG|MIN|MAX|TOTAL)\s*\(", query, re.I)):
            raise ValueError("Large-source SQL must be a bounded aggregate query")
        return super().query(query)

    def close(self):
        if not self.closed:
            self.closed = True
            self.db.close()
            self.temp.cleanup()


def analyze_streaming_sql(source: str | Path) -> dict:
    """Full-file source-bound summary; never a sample-based claim."""
    dataset = StreamingSQLDataset(source)
    try:
        return {"summary": dataset.summary,
                "source_columns": dataset.header,
                "column_aliases": [f"c{i}" for i in range(len(dataset.header))],
                "sql_verified_metrics": {},
                "dataset_intelligence": dataset.profile,
                "analysis_receipts": {"row_count_verified": True,
                                       "source_sha256": dataset.source_sha256,
                                       "coverage": "all_rows", "verified_queries": 0},
                "execution": "sqlite_disk_streaming_full_source"}
    finally:
        dataset.close()


def summarized_artifact_table(summary: dict) -> tuple[list[str], list[list[str]]]:
    """A full-source metric profile, never misrepresented as raw source rows."""
    if summary.get("source_coverage") != "full_uploaded_dataset":
        raise ValueError("Incomplete source cannot generate full-profile artifact")
    records = []
    for name, stats in list(summary.get("numeric", {}).items())[:48]:
        records.append([str(name), str(stats["count"]), str(stats["min"]),
                        str(stats["max"]), str(stats["mean"])])
    return (["source_metric", "populated_count", "full_source_min",
             "full_source_max", "full_source_mean"], records)


def verify_profile_workbook(path: Path, summary: dict):
    """Independently compare published derived Excel cells to full-source oracle."""
    from decimal import Decimal
    from openpyxl import load_workbook
    expected_header, expected_rows = summarized_artifact_table(summary)
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if "Data" not in wb.sheetnames:
            raise ValueError("Analytical workbook omitted full-source metric profile")
        rows = list(wb["Data"].iter_rows(values_only=True))
        if not rows or list(rows[0]) != expected_header or len(rows)-1 != len(expected_rows):
            raise ValueError("Analytical profile header/row count mismatch")
        for actual, expected in zip(rows[1:], expected_rows):
            if str(actual[0]) != expected[0]:
                raise ValueError("Analytical profile metric identity mismatch")
            for index in range(1,5):
                if Decimal(str(actual[index])) != Decimal(expected[index]):
                    raise ValueError("Analytical profile value contradicts original source")
    finally:
        wb.close()
    return {"verified_full_source_metrics": len(expected_rows),
            "coverage": "full_source_derived_profile_not_raw_rows"}


def render_profile_workbook(path: Path, summary: dict, title: str,
                            sections, sources: list[str]):
    """Native editable profile; label that it is NOT all raw rows.

    Every displayed metric is source-calculated. No automatically-generated
    formulas are claimed to recalculate after a source edit.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from .work_skills import csv_escape

    header, records = summarized_artifact_table(summary)
    wb = Workbook()
    overview = wb.active
    overview.title = "Summary"
    overview.append(["RIZZLER | FULL-SOURCE ANALYTICAL PROFILE"])
    overview.append([None])
    for heading, body in sections:
        overview.append([csv_escape(heading), csv_escape(body)])
    overview.append(["Scope notice", "Data sheet contains source-derived aggregates only, NOT original rows."])
    overview.append(["Original row count", summary["rows"]])
    overview.append(["Source digest (SHA-256)", summary["source_sha256"]])
    overview.append(["Source coverage", summary["source_coverage"]])
    overview.append(["Limitations", "; ".join(summary["limitations"])])
    data = wb.create_sheet("Data")
    data.append(header)
    for row in records:
        data.append([csv_escape(row[0]), int(row[1]), float(row[2]),
                     float(row[3]), float(row[4])])
    data.freeze_panes = "B2"
    data.auto_filter.ref = data.dimensions
    if sources:
        sheet = wb.create_sheet("Sources")
        for source in sources:
            sheet.append([csv_escape(source)])
    receipt = wb.create_sheet("Evidence")
    for row in (
        ("Record type", "full_source_derived_profile"),
        ("Original file SHA-256", summary["source_sha256"]),
        ("Original byte count", summary["source_bytes"]),
        ("Full source rows", summary["rows"]),
        ("Full source columns", summary["columns"]),
        ("Profile rows", len(records)),
        ("Distinct count status", "bounded fingerprints, not independently exact"),
        ("Live recalculation", "not supported: source data not embedded"),
    ):
        receipt.append(row)
    for sheet in wb:
        sheet.sheet_view.showGridLines = False
        sheet.column_dimensions["A"].width = 40
        sheet.column_dimensions["B"].width = 65 if sheet.title == "Summary" else 27
        for cell in sheet[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = PatternFill("solid", fgColor="19324C")
            cell.alignment = Alignment(wrap_text=True)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    wb.close()


def verify_profile_workbook(path: Path, summary: dict):
    """Reopen published numeric cells and reconcile with the full source."""
    from openpyxl import load_workbook
    from .work_skills import csv_escape
    header, expected_rows = summarized_artifact_table(summary)
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        if not {"Summary", "Data", "Evidence"}.issubset(workbook.sheetnames):
            raise ValueError("Profile workbook missing required traceable sheets")
        data = workbook["Data"]
        rows = list(data.iter_rows(values_only=True))
        if not rows or list(rows[0]) != header or len(rows) - 1 != len(expected_rows):
            raise ValueError("Profile workbook schema or metric count mismatch")
        for observed, expected in zip(rows[1:], expected_rows):
            if observed[0] != csv_escape(expected[0]):
                raise ValueError("Profile metric identity changed")
            for column in range(1, 5):
                if observed[column] is None or Decimal(str(observed[column])) != Decimal(expected[column]):
                    raise ValueError("Profile metric value disagrees with source oracle")
        evidence = dict(workbook["Evidence"].values)
        if (evidence.get("Original file SHA-256") != summary["source_sha256"] or
                evidence.get("Full source rows") != summary["rows"] or
                evidence.get("Full source columns") != summary["columns"] or
                evidence.get("Record type") != "full_source_derived_profile"):
            raise ValueError("Profile workbook provenance does not reconcile")
    finally:
        workbook.close()
    return {"passed": True, "verified_full_source_metrics": len(expected_rows),
            "source_sha256": summary["source_sha256"],
            "scope": "full_source_derived_profile_not_original_rows"}
