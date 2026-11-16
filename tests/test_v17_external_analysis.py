"""Research-backed analysis is valid only with an actual research stage."""
import unittest
from rizzler.work_dynamic import validate


class ExternalAnalysisTests(unittest.TestCase):
    def test_model_can_analyze_fetched_public_data(self):
        payload={"deliverables":["research","data_analysis","xlsx"],
                 "uploads":[],"evidence_scope":"external_allowed"}
        graph={"schema_version":2,"status":"ready","steps":[
            {"id":"research","tool":"research","depends_on":[],"thinking_level":"high"},
            {"id":"excel","tool":"excel","depends_on":["research"],"thinking_level":"medium"},
            {"id":"quality","tool":"quality","depends_on":["research","excel"],"thinking_level":"high"}]}
        self.assertEqual(validate(graph,payload),graph)
        incomplete={"schema_version":2,"status":"ready","steps":[
            {"id":"orchestrator","tool":"orchestrator","depends_on":[]},
            {"id":"excel","tool":"excel","depends_on":["orchestrator"]},
            {"id":"quality","tool":"quality","depends_on":["orchestrator","excel"]}]}
        with self.assertRaises(ValueError):
            validate(incomplete,payload)
