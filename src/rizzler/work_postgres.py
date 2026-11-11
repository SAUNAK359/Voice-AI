"""PostgreSQL-backed WorkStore with transactional leases and owner isolation.

The artifact bytes still use the configured shared durable directory; PostgreSQL
does not by itself make this a multi-host object-storage deployment.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path

from .work_store import WorkStore


class _Row(dict):
    def __getitem__(self, key):
        if type(key) is int:
            return list(self.values())[key]
        return super().__getitem__(key)


class _Result:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    def fetchone(self):
        value = self.cursor.fetchone()
        return _Row(value) if value is not None else None

    def fetchall(self):
        return [_Row(value) for value in self.cursor.fetchall()]

    def __iter__(self):
        return ( _Row(row) for row in self.cursor )


class _Tx:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql: str, parameters=()):
        # This is a closed set of SQL statements authored in WorkStore.
        # Never call with untrusted SQL identifiers or table names.
        stripped = " ".join(sql.strip().split())
        if stripped.startswith("SELECT * FROM jobs WHERE owner=? AND idem=?"):
            owner, key = parameters
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (owner + ":" + key,))
        elif stripped.startswith("SELECT count(*) FROM uploads WHERE owner=?"):
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("uploads:" + str(parameters[0]),))
        if stripped.startswith("SELECT * FROM jobs WHERE status='queued' OR"):
            sql += " FOR UPDATE SKIP LOCKED"
        elif stripped.startswith("SELECT p.*,j.payload,j.fingerprint FROM proposals"):
            sql += " FOR UPDATE OF p SKIP LOCKED"
        elif stripped.startswith("SELECT * FROM jobs WHERE id=?"):
            sql += " FOR UPDATE"
        elif stripped.startswith("SELECT * FROM jobs WHERE owner=? AND id=?"):
            sql += " FOR UPDATE"
        elif stripped.startswith("SELECT * FROM proposals WHERE id=? AND owner=?"):
            sql += " FOR UPDATE"
        cursor = self.connection.execute(sql.replace("?", "%s"), parameters)
        return _Result(cursor)

    def executescript(self, ddl: str):
        # WorkStore's fixed SQLite DDL is normalized to PostgreSQL 14+.
        self.connection.execute("SELECT pg_advisory_xact_lock(91370123)")
        ddl = ddl.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        ddl = ddl.replace("REAL NOT NULL", "DOUBLE PRECISION NOT NULL")
        for statement in ddl.split(";"):
            if statement.strip():
                self.connection.execute(statement)


class PostgresWorkStore(WorkStore):
    def __init__(self, root: str | Path, dsn: str, upload_scanner=None):
        if not isinstance(dsn, str) or not dsn.startswith(("postgresql://", "postgres://")):
            raise ValueError("PostgreSQL DSN required")
        self.dsn = dsn
        super().__init__(root, upload_scanner=upload_scanner)

    @contextmanager
    def _tx(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install production postgres extras") from exc
        # Connect per transaction (not per SQL statement), with pool/proxy
        # recommended for high-throughput deployments.
        connection = psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5)
        try:
            with connection.transaction():
                yield _Tx(connection)
        finally:
            connection.close()
