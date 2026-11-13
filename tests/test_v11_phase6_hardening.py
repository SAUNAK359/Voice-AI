"""Phase 6 recovery hardening: atomic leases, WAL backup and readiness.

All tests are offline. They do not claim real cloud/GPU load qualification.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tempfile
import unittest
from unittest.mock import patch

from rizzler.backup import backup, restore, _publish_directory_noreplace
from rizzler.pdf_documents import PDFStore, DocumentConflict
from rizzler.pdf_analysis import PDFResearch


OWNER = "phase6_hardened_owner"
SECRET = "phase6-hardened-independent-visual-encryption-12345"


class BackupHardeningTests(unittest.TestCase):
    def test_nested_sqlite_wal_is_checkpointed_and_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "work"
            nested = root / "visuals" / "pdfs"
            nested.mkdir(parents=True)
            source = nested / "pdf_ingestion.sqlite3"
            con = sqlite3.connect(source)
            try:
                self.assertEqual(con.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
                con.execute("CREATE TABLE records(page INTEGER, evidence TEXT)")
                con.execute("INSERT INTO records VALUES(77, 'encrypted checkpoint')")
                con.commit()
                archive = Path(temp) / "snapshot.tar.gz"
                manifest = backup(root, archive)
                names = [entry["path"] for entry in manifest["files"]]
                self.assertIn("visuals/pdfs/pdf_ingestion.sqlite3", names)
                self.assertFalse(any(name.endswith(("-wal", "-shm")) for name in names))
                restored = Path(temp) / "restored"
                receipt = restore(archive, restored)
                self.assertEqual(receipt, manifest)
                with sqlite3.connect(restored / "visuals" / "pdfs" / "pdf_ingestion.sqlite3") as db:
                    row = db.execute("SELECT page,evidence FROM records").fetchone()
                self.assertEqual(row, (77, "encrypted checkpoint"))
            finally:
                con.close()

    def test_backup_does_not_overwrite_an_existing_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "work"
            (root / "artifacts").mkdir(parents=True)
            (root / "artifacts" / "data.txt").write_text("valid report")
            output = Path(temp) / "old-backup.tar.gz"
            output.write_bytes(b"keep old verified backup")
            with self.assertRaises(ValueError):
                backup(root, output)
            self.assertEqual(output.read_bytes(), b"keep old verified backup")

    def test_restore_publish_refuses_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            staged = root / "verified"
            target = root / "destination"
            staged.mkdir()
            target.mkdir()
            (staged / "report.txt").write_text("new")
            (target / "report.txt").write_text("old")
            with self.assertRaises(ValueError):
                _publish_directory_noreplace(staged, target)
            self.assertEqual((target / "report.txt").read_text(), "old")
            self.assertEqual((staged / "report.txt").read_text(), "new")
            committed = root / "new-target"
            _publish_directory_noreplace(staged, committed)
            self.assertEqual((committed / "report.txt").read_text(), "new")
            self.assertFalse(staged.exists())

    def test_corrupted_nested_sqlite_prevents_archive_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "work"
            (root / "private_memory").mkdir(parents=True)
            (root / "private_memory" / "memory.sqlite3").write_bytes(b"invalid sqlite bytes")
            destination = Path(temp) / "snapshot.tar.gz"
            with self.assertRaises(sqlite3.DatabaseError):
                backup(root, destination)
            self.assertFalse(destination.exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO required")
    def test_nonregular_private_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "work"
            (root / "uploads").mkdir(parents=True)
            os.mkfifo(root / "uploads" / "blocking.pipe")
            with self.assertRaises(ValueError):
                backup(root, Path(temp) / "snapshot.tar.gz")


class PDFLeaseHardeningTests(unittest.TestCase):
    def test_same_chunk_concurrent_retries_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PDFStore(Path(temp) / "pdf", SECRET)
            doc = store.create(OWNER, "concurrent.pdf")
            packet = b"%PDF-" + b"x" * 1000
            digest = hashlib.sha256(packet).hexdigest()
            with ThreadPoolExecutor(max_workers=12) as executor:
                receipts = list(executor.map(
                    lambda _: store.append(OWNER, doc["id"], 0, packet, digest), range(30)))
            self.assertEqual([r["uploaded_chunks"] for r in receipts], [1] * 30)
            self.assertEqual(store.status(OWNER, doc["id"])["received_bytes"], len(packet))

    def test_only_one_worker_wins_pdf_and_validation_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PDFStore(Path(temp) / "pdf", SECRET)
            doc = store.create(OWNER, "concurrent.pdf")
            packet = b"%PDF-" + b"x" * 1000
            store.append(OWNER, doc["id"], 0, packet,
                         hashlib.sha256(packet).hexdigest())
            store.request_finalize(OWNER, doc["id"])
            def validation(_):
                try:
                    return store.begin_validation(OWNER, doc["id"])
                except DocumentConflict:
                    return None
            with ThreadPoolExecutor(max_workers=12) as executor:
                winners = [t for t in executor.map(validation, range(32)) if t]
            self.assertEqual(len(winners), 1)
            with store.db() as db:
                db.execute("UPDATE docs SET status='queued',lease=NULL,lease_until=0 WHERE id=?",
                           (doc["id"],))
            def ingestion(_):
                try:
                    return store.claim(OWNER, doc["id"])
                except DocumentConflict:
                    return None
            with ThreadPoolExecutor(max_workers=12) as executor:
                winners = [t for t in executor.map(ingestion, range(32)) if t]
            self.assertEqual(len(winners), 1)

    def test_expired_pdf_lease_revokes_old_worker_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PDFStore(Path(temp) / "pdf", SECRET)
            doc = store.create(OWNER, "fenced.pdf")
            with store.db() as db:
                db.execute("UPDATE docs SET status='queued' WHERE id=?", (doc["id"],))
            first = store.claim(OWNER, doc["id"])
            with store.db() as db:
                db.execute("UPDATE docs SET lease_until=0 WHERE id=?", (doc["id"],))
            second = store.claim(OWNER, doc["id"])
            self.assertNotEqual(first, second)
            with self.assertRaises(DocumentConflict):
                store.put_page(OWNER, doc["id"], first, 0, "stale", 1)
            store.put_page(OWNER, doc["id"], second, 0, "current", 1)

    def test_concurrent_research_claims_are_fenced(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PDFStore(Path(temp) / "pdf", SECRET)
            doc = store.create(OWNER, "report.pdf")
            with store.db() as db:
                db.execute("UPDATE docs SET status='complete',pages=1,processed=1 WHERE id=?",
                           (doc["id"],))
            agent = PDFResearch(store, object())
            run = agent.submit(OWNER, doc["id"], "Summarize this page")
            def attempt(_):
                try:
                    return agent._claim(OWNER, run["id"])
                except DocumentConflict:
                    return None
            with ThreadPoolExecutor(max_workers=12) as executor:
                winners = [t for t in executor.map(attempt, range(32)) if t]
            self.assertEqual(len(winners), 1)


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in
                         ("fastapi", "httpx", "numpy", "PIL", "fitz", "cryptography")),
                     "Application integration extras required")
class ReadinessHardeningTests(unittest.TestCase):
    def test_corrupt_pdf_database_fails_readiness_without_leaking_details(self):
        from fastapi.testclient import TestClient
        import numpy as np
        from rizzler.api import create_app
        from rizzler.config import Settings
        from rizzler.voice import ProviderSet

        class ASR:
            def transcribe(self, wave):
                return "hello"

        class LLM:
            async def stream(self, text, history):
                yield "Hello"

        class TTS:
            def synthesize(self, phrase):
                return np.full(1200, 250, dtype="<i2").tobytes()

        with tempfile.TemporaryDirectory() as temp:
            environment = {
                "RIZZLER_DEPLOYMENT_MODE": "demo",
                "RIZZLER_VISUAL_ENABLED": "1",
                "RIZZLER_VISUAL_ROOT": str(Path(temp) / "visual"),
                "RIZZLER_VISUAL_KEY": SECRET,
            }
            with patch.dict(os.environ, environment, clear=True):
                app = create_app(Settings(access_key="phase6-hardening-test-key"),
                                 ProviderSet(ASR(), LLM(), TTS()))
                with TestClient(app) as client:
                    self.assertEqual(client.get("/ready").status_code, 200)
                    store_path = app.state.pdf_store.path
                    store_path.write_bytes(b"corrupted database")
                    response = client.get("/ready")
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json()["detail"], "Dependency not ready")


if __name__ == "__main__":
    unittest.main()
