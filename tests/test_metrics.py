import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rizzler.metrics import summarize,percentile_nearest_rank,summarize_run

class MetricsTests(unittest.TestCase):
    def test_median_p95(self):
        records=[{'outcome':'ok','asr_ms':v} for v in range(1,21)]
        got=summarize(records,'asr_ms')
        self.assertEqual(got['count'],20)
        self.assertEqual(got['median_ms'],10.5)
        self.assertEqual(got['p95_ms'],19)
    def test_bad_runs_not_counted(self):
        got=summarize([{'outcome':'error','asr_ms':500}],'asr_ms')
        self.assertEqual(got['count'],0)
        self.assertIsNone(got['median_ms'])
    def test_empty_run(self):
        self.assertEqual(summarize_run([])['successful'],0)
    def test_zero_allowed(self):
        self.assertEqual(percentile_nearest_rank([0.0],95),0)
