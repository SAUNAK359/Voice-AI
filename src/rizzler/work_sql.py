"""Read-only, bounded SQLite analytics against an uploaded CSV/XLSX dataset.

No untrusted database connections, arbitrary SQL execution or external file reads.
A specialist may query only a temporary in-memory representation of the input.
"""
from __future__ import annotations
import sqlite3

from .work_skills import analyze, read_dataset


def _load(db, header, rows):
    columns = ", ".join(f"c{i} TEXT NOT NULL" for i in range(len(header)))
    db.execute("CREATE TABLE dataset (row_number INTEGER PRIMARY KEY" +
               (", " + columns if columns else "") + ")")
    placeholders = ",".join("?" for _ in range(len(header) + 1))
    db.executemany("INSERT INTO dataset VALUES (" + placeholders + ")",
                   ((i, *row) for i, row in enumerate(rows, 1)))


def _allow_select(action, table, *args):
    return (sqlite3.SQLITE_OK if
            (action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION,
                        sqlite3.SQLITE_TRANSACTION) or
             (action == sqlite3.SQLITE_READ and table == "dataset"))
            else sqlite3.SQLITE_DENY)


def analyze_sql(source):
    header, rows = read_dataset(source)
    if len(rows) > 10000 or len(header) > 50:
        raise ValueError("Input exceeds bounded analytics policy")
    numeric = analyze(header, rows)
    with sqlite3.connect(":memory:") as db:
        _load(db, header, rows)
        db.set_authorizer(_allow_select)
        progress = [0]
        def budget():
            progress[0] += 1
            return int(progress[0] > 5000)
        db.set_progress_handler(budget, 1000)
        sql_rows = db.execute("SELECT COUNT(*) FROM dataset").fetchone()[0]
        if sql_rows != numeric["rows"]:
            raise ValueError("SQL rows do not reconcile with source dataset")
        verified = {}
        for i, name in enumerate(header):
            metrics = numeric["numeric"].get(name)
            if metrics is None:
                continue
            col = f"c{i}"  # Only generated identifiers; never user-controlled SQL.
            q = (f"SELECT COUNT(NULLIF(TRIM({col}), '')), "
                 f"MIN(CAST(NULLIF(TRIM({col}), '') AS REAL)), "
                 f"MAX(CAST(NULLIF(TRIM({col}), '') AS REAL)), "
                 f"AVG(CAST(NULLIF(TRIM({col}), '') AS REAL)) FROM dataset")
            count, low, high, avg = db.execute(q).fetchone()
            if (count != metrics["count"] or
                abs(low - metrics["min"]) > 0.00001 or
                abs(high - metrics["max"]) > 0.00001 or
                abs(avg - metrics["mean"]) > 0.00001):
                raise ValueError("Independent SQL aggregation differs from deterministic profiling")
            verified[name] = {"count": count, "mean": round(avg, 6)}
    return {"summary": {**numeric, "sql_row_count": sql_rows,
                         "sql_numeric_columns_verified": len(verified)},
            "sql_verified_metrics": verified, "source_columns": header,
            "column_aliases": [f"c{i}" for i in range(len(header))],
            "execution": "sqlite_readonly_in_memory",
            "limits": {"rows": 10000, "columns": 50}}


def execute_readonly_sql(header: list[str], rows: list[list[str]], query: str,
                         params: tuple = (), max_rows: int = 100):
    """Small trusted-memory SQL tool with strict read-only authorizer and progress bound."""
    if (not isinstance(query, str) or len(query) > 1500 or not 1 <= max_rows <= 1000
            or len(rows) > 10000 or len(header) > 50):
        raise ValueError("Invalid SQL execution budget")
    if not query.lstrip().upper().startswith("SELECT "):
        raise PermissionError("SQL must be read-only SELECT")
    with sqlite3.connect(":memory:") as db:
        _load(db, header, rows)
        db.set_authorizer(_allow_select)
        budget = [0]
        def progress():
            budget[0] += 1
            return 1 if budget[0] > 200 else 0
        db.set_progress_handler(progress, 1000)
        result = db.execute(query, params).fetchmany(max_rows + 1)
        if len(result) > max_rows:
            raise ValueError("SQL output exceeded row limit")
        return result
