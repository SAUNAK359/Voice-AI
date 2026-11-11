"""PostgreSQL Work Agent tests; executed by dedicated GitHub CI service."""
from __future__ import annotations
import concurrent.futures
import os
import time
import pytest

psycopg = pytest.importorskip("psycopg")
from rizzler.work_postgres import PostgresWorkStore
from rizzler.work_store import Conflict, StaleLease
from rizzler.artifacts import verify_artifact

DSN = os.environ.get("RIZZLER_TEST_POSTGRES_URL")
if not DSN:
    pytest.skip("requires dedicated temporary PostgreSQL service", allow_module_level=True)


@pytest.fixture
def store(tmp_path):
    db = PostgresWorkStore(tmp_path / "files", DSN)
    with psycopg.connect(DSN) as con:
        con.execute("TRUNCATE TABLE proposals, artifacts, uploads, events, jobs RESTART IDENTITY CASCADE")
    yield db


def submit(store, idem):
    return store.submit("owner_1", "Write an informative stand-alone report.",
                        ["md"], idem, [])


def test_postgres_schema_roundtrip_and_idempotency(store):
    original = submit(store, "request001")
    other = PostgresWorkStore(store.root, DSN)
    assert submit(other, "request001")["id"] == original["id"]
    with pytest.raises(Conflict):
        other.submit("owner_1", "Another report with different objectives",
                     ["md"], "request001", [])
    assert len(other.list_jobs("owner_1")) == 1
    assert len(other.events("owner_1", original["id"])) == 1


def test_postgres_concurrent_claims_do_not_duplicate_work(store):
    ids = {submit(store, "req_" + str(i).zfill(8))["id"] for i in range(5)}
    def claim(i):
        worker = PostgresWorkStore(store.root, DSN)
        return worker.claim("w" + str(i), lease_seconds=30)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        claims = list(pool.map(claim, range(5)))
    assert {item["id"] for item in claims} == ids
    assert len({item["fence"] for item in claims}) == 1


def test_postgres_verified_artifact_commit_and_owner_isolation(store, tmp_path):
    job = submit(store, "req_commit001")
    claim = store.claim("worker", 30)
    stage = tmp_path / "stage"
    stage.mkdir()
    path = stage / "md.md"
    path.write_text("# Heading\nA meaningful report with verified content.", encoding="utf-8")
    receipt = verify_artifact(path, "md")
    store.renew(job["id"], "worker", claim["fence"], "rendering")
    store.finish(job["id"], "worker", claim["fence"], "The report completed.",
                 [receipt], stage)
    assert store.get("owner_1", job["id"])["status"] == "completed"
    artifact = store.artifacts("owner_1", job["id"])[0]
    p, _ = store.artifact("owner_1", artifact["id"])
    assert p.read_bytes() == path.read_bytes()
    from rizzler.work_store import Missing
    with pytest.raises(Missing):
        store.artifact("owner_2", artifact["id"])


def test_postgres_fenced_recovery_and_cancel(store, monkeypatch):
    import rizzler.work_store as module
    now = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    job = submit(store, "req_lost001")
    old = store.claim("old", 10)
    now[0] += 11
    new = store.claim("new", 10)
    assert new["id"] == job["id"] and new["fence"] == old["fence"] + 1
    with pytest.raises(StaleLease):
        store.renew(job["id"], "old", old["fence"])
    store.cancel("owner_1", job["id"])
    store.fail(job["id"], "new", new["fence"])
    assert store.get("owner_1", job["id"])["status"] == "cancelled"
