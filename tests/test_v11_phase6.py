"""V11 Phase 6: offline disaster-recovery, budget concurrency, workload limits."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rizzler.backup import backup, restore
from rizzler.production_guard import (
    BudgetLedger, BudgetExceeded, budget_from_environment, reserve_provider_call)


class ProductionHardeningTests(unittest.TestCase):
    def test_full_private_state_backup_and_atomic_restore(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"running"
            root.mkdir()
            files={
                "uploads/account/data.csv":b"alpha,beta\n1,2",
                "artifacts/report.pdf":b"%PDF-test fixture bytes",
                "private_memory/memory.sqlite3":b"encrypted memory fixture",
                "visuals/visual_v11.sqlite3":b"encrypted images fixture",
                "visuals/pdfs/pdf_ingestion.sqlite3":b"encrypted document fixture",
                "visuals/pdfs/payload.bin":b"0"*2_000_000,
            }
            for name,content in files.items():
                path=root/name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(content)
            with sqlite3.connect(root/"ai_reservations.sqlite3") as db:
                db.execute("CREATE TABLE demo(id INTEGER PRIMARY KEY,usd INTEGER)")
                db.execute("INSERT INTO demo(usd) VALUES(10)")
            files["ai_reservations.sqlite3"]=(root/"ai_reservations.sqlite3").read_bytes()
            archive=Path(d)/"snapshot.tar.gz"
            with patch.object(Path,"read_bytes",side_effect=AssertionError(
                    "Backup must stream instead of loading complete PDF")):
                manifest=backup(root,archive)
            self.assertEqual(len(manifest["files"]),len(files))
            self.assertEqual(manifest["schema_version"],2)
            restored=Path(d)/"restored"
            verify=restore(archive,restored)
            self.assertEqual(verify,manifest)
            for name,content in files.items():
                self.assertEqual((restored/name).read_bytes(),content)
            self.assertRaises(ValueError,restore,archive,restored)

    def test_corruption_cannot_leave_partial_restore_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"work"
            root.mkdir()
            (root/"uploads").mkdir()
            (root/"uploads"/"valid.bin").write_bytes(b"verified")
            good=Path(d)/"good.tar.gz"
            backup(root,good)
            bad=Path(d)/"bad.tar.gz"
            with tarfile.open(good,"r:gz") as archive,tarfile.open(bad,"w:gz") as damaged:
                for member in archive.getmembers():
                    contents=archive.extractfile(member).read()
                    if member.name=="data/uploads/valid.bin":
                        contents=b"tampered"
                    info=tarfile.TarInfo(member.name)
                    info.size=len(contents)
                    damaged.addfile(info,io.BytesIO(contents))
            target=Path(d)/"restored"
            with self.assertRaises(ValueError):
                restore(bad,target)
            self.assertFalse(target.exists())

    def test_symlinks_and_archive_path_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"work"
            root.mkdir()
            (root/"uploads").mkdir()
            external=Path(d)/"secret"
            external.write_text("secret")
            (root/"uploads"/"bad").symlink_to(external)
            with self.assertRaises(ValueError):
                backup(root,Path(d)/"bad.tar.gz")
            archive=Path(d)/"attack.tar.gz"
            data=b"payload"
            manifest={"schema_version":2,"files":[{
                "path":"uploads/../../escape",
                "bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}]}
            with tarfile.open(archive,"w:gz") as tar:
                for name,content in (
                    ("data/uploads/../../escape",data),
                    ("MANIFEST.json",json.dumps(manifest).encode())):
                    info=tarfile.TarInfo(name)
                    info.size=len(content)
                    tar.addfile(info,io.BytesIO(content))
            destination=Path(d)/"restore"
            with self.assertRaises(ValueError):
                restore(archive,destination)
            self.assertFalse(destination.exists())
            self.assertEqual(external.read_text(),"secret")

    def test_global_ai_budget_is_durable_and_atomic_across_threads(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"budget.sqlite3"
            def reserve(index):
                ledger=BudgetLedger(path,1.00,0.10)
                try:
                    ledger.reserve(("voice","vision","work","research")[index%4])
                    return True
                except BudgetExceeded:
                    return False
            with ThreadPoolExecutor(max_workers=12) as pool:
                accepted=list(pool.map(reserve,range(40)))
            self.assertEqual(sum(accepted),10)
            after=BudgetLedger(path,1.00,0.10).snapshot()
            self.assertAlmostEqual(after["reserved_usd"],1.0)
            self.assertEqual(sum(after["requests"].values()),10)
            with self.assertRaises(BudgetExceeded):
                BudgetLedger(path,1.00,0.10).reserve("voice")

    def test_ai_budget_optional_and_misconfiguration_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            budget_from_environment.cache_clear()
            with patch.dict("os.environ",{},clear=True):
                self.assertIsNone(budget_from_environment())
                reserve_provider_call("vision")
            with patch.dict("os.environ",{
                "RIZZLER_AI_DAILY_BUDGET_USD":"0.10",
                "RIZZLER_AI_BUDGET_ROOT":d},clear=True):
                budget_from_environment.cache_clear()
                with self.assertRaises(ValueError):
                    reserve_provider_call("voice")
            with patch.dict("os.environ",{
                "RIZZLER_AI_DAILY_BUDGET_USD":"0.20",
                "RIZZLER_AI_RESERVATION_PER_CALL_USD":"0.10",
                "RIZZLER_AI_BUDGET_ROOT":d},clear=True):
                budget_from_environment.cache_clear()
                reserve_provider_call("vision")
                reserve_provider_call("research")
                with self.assertRaises(BudgetExceeded):
                    reserve_provider_call("work")
            budget_from_environment.cache_clear()

    def test_reject_invalid_cost_bound_or_storage(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"cost.db"
            for daily,per_call in ((0,0.01),(-1,.01),(.1,0),(.1,.2)):
                with self.assertRaises(ValueError):
                    BudgetLedger(path,daily,per_call)
            with self.assertRaises(ValueError):
                BudgetLedger("relative.db",1,.1)


if __name__=="__main__":
    unittest.main()
