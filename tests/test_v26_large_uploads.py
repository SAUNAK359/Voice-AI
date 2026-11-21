"""V26 streamed Work ingestion: scope, integrity, caps and fail-closed scanning.

This is an offline transport/storage qualification, not a 200 MB
full-analytics or human-reviewed artifact qualification.
"""
from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_large_uploads import (
    HARD_LIMIT, UploadTooLarge, spool_request, upload_limit,
    validate_uploaded_file)
from rizzler.work_store import WorkStore, Missing
from rizzler.upload_scan import ScanUnavailable


def csv_data(n=10_000):
    return b"period,value\n" + b"Q1,12\n" * n


def xlsx_bytes(extra=None):
    obj=BytesIO()
    with zipfile.ZipFile(obj,"w") as z:
        z.writestr("xl/workbook.xml",b"<workbook/>")
        z.writestr("[Content_Types].xml",b"<Types/>")
        if extra:
            z.writestr(extra,b"attacker")
    return obj.getvalue()


class StreamIngestionTests(unittest.TestCase):
    def test_rollout_is_off_and_maximum_is_hard_capped(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(upload_limit(),8_000_000)
        with patch.dict(os.environ,{"RIZZLER_V26_LARGE_UPLOADS":"1"}):
            self.assertEqual(upload_limit(),HARD_LIMIT)
        with patch.dict(os.environ,{"RIZZLER_V26_LARGE_UPLOADS":"1",
                                     "RIZZLER_V26_MAX_UPLOAD_BYTES":"200000001"}):
            with self.assertRaises(ValueError):upload_limit()

    def test_streamed_content_is_hashed_and_does_not_require_ram_accumulation(self):
        with TemporaryDirectory() as temp:
            async def chunks():
                for _ in range(12):
                    yield b"period,value\nQ1,12\n" * 60_000
            path=Path(temp)/"large.part"
            size,digest=asyncio.run(spool_request(chunks(),path,maximum=HARD_LIMIT))
            self.assertGreater(size,8_000_000)
            from rizzler.work_large_uploads import sha256_file
            self.assertEqual(sha256_file(path),digest)

    def test_overlimit_stream_is_unlinked_before_registration(self):
        async def chunks():
            yield b"x"*5_000_000
            yield b"y"*4_000_001
        with TemporaryDirectory() as temp:
            path=Path(temp)/"over.part"
            with self.assertRaises(UploadTooLarge):
                asyncio.run(spool_request(chunks(),path,maximum=8_000_000))
            self.assertFalse(path.exists())

    def test_exact_cap_rejects_oversized_disk_file_without_reading(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/"huge.csv"
            with path.open("wb") as handle:
                handle.truncate(HARD_LIMIT+1)
            with self.assertRaises(UploadTooLarge):
                validate_uploaded_file(path,"huge.csv",maximum=HARD_LIMIT)

    def test_verified_private_file_and_owner_isolation(self):
        with TemporaryDirectory() as temp, patch.dict(
                os.environ,{"RIZZLER_V26_LARGE_UPLOADS":"1"}):
            store=WorkStore(Path(temp)/"work")
            stage=store.prepare_upload_staging()
            data=csv_data()
            stage.write_bytes(data)
            receipt=store.register_upload_file(
                "owner_alpha","data.csv",stage,
                expected_sha256=hashlib.sha256(data).hexdigest())
            self.assertFalse(stage.exists())
            self.assertEqual(store.upload("owner_alpha",receipt["id"]).read_bytes(),data)
            with self.assertRaises(Missing):store.upload("owner_beta",receipt["id"])

    def test_digest_corruption_and_external_path_are_rejected(self):
        with TemporaryDirectory() as temp, patch.dict(
                os.environ,{"RIZZLER_V26_LARGE_UPLOADS":"1"}):
            store=WorkStore(Path(temp)/"work")
            stage=store.prepare_upload_staging()
            stage.write_bytes(csv_data())
            with self.assertRaises(ValueError):
                store.register_upload_file("owner_alpha","data.csv",stage,
                    expected_sha256="0"*64)
            external=Path(temp)/"external.csv"
            external.write_bytes(csv_data())
            with self.assertRaises(ValueError):
                store.register_upload_file("owner_alpha","data.csv",external,
                    expected_sha256=hashlib.sha256(external.read_bytes()).hexdigest())

    def test_byte_only_scanner_is_not_bypassed(self):
        with TemporaryDirectory() as temp,patch.dict(
                os.environ,{"RIZZLER_V26_LARGE_UPLOADS":"1"}):
            store=WorkStore(Path(temp)/"work",upload_scanner=lambda _:None)
            stage=store.prepare_upload_staging()
            data=csv_data()
            stage.write_bytes(data)
            with self.assertRaises(ScanUnavailable):
                store.register_upload_file("owner_alpha","data.csv",stage,
                    expected_sha256=hashlib.sha256(data).hexdigest())

    def test_scanner_rejection_does_not_publish_accepted_upload(self):
        def reject(_):
            raise ScanUnavailable("Untrusted data blocked")
        with TemporaryDirectory() as temp,patch.dict(
                os.environ,{"RIZZLER_V26_LARGE_UPLOADS":"1"}):
            store=WorkStore(Path(temp)/"work",upload_scanner=lambda _:None,
                            upload_scanner_file=reject)
            stage=store.prepare_upload_staging()
            data=csv_data()
            stage.write_bytes(data)
            with self.assertRaises(ScanUnavailable):
                store.register_upload_file("owner_alpha","data.csv",stage,
                    expected_sha256=hashlib.sha256(data).hexdigest())
            with store._tx() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0],0)

    def test_archive_path_traversal_is_rejected(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/"unsafe.xlsx"
            path.write_bytes(xlsx_bytes("../hidden.xml"))
            with self.assertRaises(ValueError):
                validate_uploaded_file(path,"unsafe.xlsx",maximum=HARD_LIMIT)

    def test_owner_size_quota_cannot_be_silently_extended(self):
        with TemporaryDirectory() as temp,patch.dict(
                os.environ,{"RIZZLER_V26_LARGE_UPLOADS":"1"}):
            store=WorkStore(Path(temp)/"work")
            with store._tx() as conn:
                conn.execute("INSERT INTO uploads VALUES(?,?,?,?,?,?)",
                             ("f"*32,"owner_alpha","old.csv","0"*64,
                              600_000_000,123))
            stage=store.prepare_upload_staging()
            data=csv_data()
            stage.write_bytes(data)
            from rizzler.work_store import Conflict
            with self.assertRaises(Conflict):
                store.register_upload_file("owner_alpha","data.csv",stage,
                    expected_sha256=hashlib.sha256(data).hexdigest())

if __name__=="__main__":
    unittest.main()
