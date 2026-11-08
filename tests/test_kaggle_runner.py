"""Offline validation of the Kaggle benchmark entry point."""
import subprocess
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
class KaggleRunnerTests(unittest.TestCase):
    def test_dry_run_needs_no_gpu_or_credentials(self):
        p=subprocess.run([sys.executable,str(ROOT/"scripts/run_kaggle_benchmarks.py"),
            "--dry-run","--output-dir","/tmp/unused-rizzler-benchmark-run",
            "--repeat","5","--asr-samples","20"],check=True,text=True,capture_output=True,timeout=20)
        self.assertIn('"no_live_measurements_created": true',p.stdout)
