"""PostgreSQL Work Agent tests; executed by dedicated GitHub CI service."""
from __future__ import annotations
import concurrent.futures
import os
import time
import importlib.util
import unittest

if importlib.util.find_spec("pytest") is None or importlib.util.find_spec("psycopg") is None:
    raise unittest.SkipTest("Requires PostgreSQL integration dependencies")
import pytest
import psycopg
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
    # V13 executes at most one project per owner across concurrent workers.
    active=[item for item in claims if item is not None]
    assert len(active)==1
    assert active[0]["id"] in ids
    assert len([j for j in store.list_jobs("owner_1") if j["status"]=="queued"])==4
    assert len([j for j in store.list_jobs("owner_1") if j["status"]=="running"])==1


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


def test_postgres_and_s3_across_independent_worker_roots(store, tmp_path):
    """API and worker have no shared artifacts directory."""
    from pathlib import Path
    from rizzler.work_objects import S3Objects
    from rizzler.artifacts import verify_artifact
    class FakeS3:
        def __init__(self): self.data = {}
        def upload_fileobj(self, stream, bucket, key, ExtraArgs):
            self.data[key] = (stream.read(), ExtraArgs["Metadata"])
        def head_object(self, Bucket, Key):
            raw, meta = self.data[Key]
            return {"ContentLength": len(raw), "Metadata": meta}
        def download_file(self, bucket, key, filename):
            Path(filename).write_bytes(self.data[key][0])
    remote = S3Objects("private-test-bucket", client=FakeS3())
    api = PostgresWorkStore(tmp_path/"api", DSN, object_store=remote)
    worker = PostgresWorkStore(tmp_path/"worker", DSN, object_store=remote)
    upload = api.register_upload("owner_1", "dataset.csv", b"name,value\\nA,10\\nB,15\\n")
    job = api.submit("owner_1", "Generate a verified report for the dataset.",
                     ["md"], "separatehost001", [upload["id"]])
    assert not (worker.root / "uploads").exists()
    assert b"name,value" in worker.upload("owner_1", upload["id"]).read_bytes()
    claim = worker.claim("worker-B", 30)
    assert claim["id"] == job["id"]
    stage = tmp_path/"stage-remote"
    stage.mkdir()
    output = stage/"md.md"
    output.write_text("# Analysis\\nGrounded dataset summary for an independent worker.", encoding="utf-8")
    receipt = verify_artifact(output, "md")
    worker.finish(job["id"], "worker-B", claim["fence"], "Completed verified analysis.",
                  [receipt], stage)
    remote_download, _ = api.artifact("owner_1", api.artifacts("owner_1",job["id"])[0]["id"])
    assert remote_download.read_bytes() == output.read_bytes()
