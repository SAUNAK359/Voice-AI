"""Read-only, bounded SQLite analytics against an uploaded CSV/XLSX dataset.

No untrusted database connections, arbitrary SQL execution or external file reads.
A specialist may query only a temporary in-memory representation of the input.
"""
from __future__ import annotations
import sqlite3

from .work_skills import analyze, read_dataset


def analyze_sql(source):
    header, rows = read_dataset(source)
    if len(rows) > 10000 or len(header) > 50:
        raise ValueError("Input exceeds bounded analytics policy")
    numeric = analyze(header, rows)
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE dataset (row_number INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        db.executemany("INSERT INTO dataset VALUES (?, ?)",
                       ((i, "\x1f".join(row)) for i, row in enumerate(rows, 1)))
        db.set_authorizer(lambda action, table, *args: sqlite3.SQLITE_OK
                          if (action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION,
                                          sqlite3.SQLITE_TRANSACTION) or
                              (action == sqlite3.SQLITE_READ and table == "dataset"))
                          else sqlite3.SQLITE_DENY)
        db.set_progress_handler(lambda: 1, 10000)  # Bounded work, no arbitrary queries.
        sql_rows = db.execute("SELECT COUNT(*) FROM dataset").fetchone()[0]
    return {"summary": {**numeric, "sql_row_count": sql_rows},
            "source_columns": header, "execution": "sqlite_readonly_in_memory",
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
        db.execute("CREATE TABLE dataset (row_number INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        db.executemany("INSERT INTO dataset VALUES (?, ?)",
                       ((i, "\x1f".join(row)) for i, row in enumerate(rows, 1)))
        db.set_authorizer(lambda action, table, *args: sqlite3.SQLITE_OK
                          if (action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION,
                                          sqlite3.SQLITE_TRANSACTION) or
                              (action == sqlite3.SQLITE_READ and table == "dataset"))
                          else sqlite3.SQLITE_DENY)
        budget = [0]
        def progress():
            budget[0] += 1
            return 1 if budget[0] > 200 else 0
        db.set_progress_handler(progress, 1000)
        result = db.execute(query, params).fetchmany(max_rows + 1)
        if len(result) > max_rows:
            raise ValueError("SQL output exceeded row limit")
        return result
