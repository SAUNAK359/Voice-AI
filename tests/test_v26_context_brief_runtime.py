"""Reproduce Kaggle's context overflow without dropping critical proof nodes."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_context_fabric import create_fabric,node,ContextBudgetExceeded
from rizzler.work_context_intelligence import context_brief

FLAGS={
    "RIZZLER_V26_CONTEXT_FABRIC":"1",
    "RIZZLER_V26_OUTCOME_PHASES":"1",
    "RIZZLER_V26_INSIGHT_GRAPH":"1",
}


def graph(extra_requirements=0):
    nodes=[
        node(id="goal:original",kind="goal",status="approved",
             data={"objective":"Produce a source-grounded synthetic analysis."}),
        node(id="source:dataset",kind="source",status="attributed",
             data={"source_sha256":"a"*64,
                   "provenance":"independently_computed_summary_only"}),
        node(id="metric:imports",kind="metric",status="computed_summary",
             dependencies=["source:dataset"],
             data={"critical":True,"name":"imports","value":600.0,
                   "unit":"not_declared_by_source",
                   "period":"observed_uploaded_dataset",
                   "source_table_sha256":"a"*64}),
        node(id="uncertainty:units",kind="uncertainty",status="unknown",
             dependencies=["goal:original"],data={
                 "caveat":"No declared physical or currency units."}),
    ]
    for i in range(4+extra_requirements):
        nodes.append(node(id="requirement:g"+str(i),kind="requirement",
                          status="pending",dependencies=["goal:original"],
                          data={"obligation":"Requirement "+str(i)+": "+
                                "Every authorized metric needs traceable evidence."}))
    for i in range(28):
        nodes.append(node(id="narrative_candidate:"+str(i),
                          kind="narrative_candidate",status="candidate",
                          dependencies=["goal:original"],
                          data={"content":"Synthetic narrative, not source proof. " * 32,
                                "section":i}))
    return create_fabric(owner="v26_owner",job_id="v26_job",
                         goal_digest="b"*64,nodes=nodes)


class V26ContextBriefRuntimeTests(unittest.TestCase):
    def test_full_proof_retained_with_optional_content_evicted(self):
        g=graph()
        with patch.dict(os.environ,FLAGS,clear=True):
            payload=context_brief({"work_graph":g},specialist="excel",
                                  max_chars=15000)
        parsed=json.loads(payload[payload.index("{"):])
        kinds={item["kind"] for item in parsed["nodes"]}
        ids={item["id"] for item in parsed["nodes"]}
        self.assertTrue({"goal","requirement","uncertainty","metric","source"}<=kinds)
        self.assertIn("metric:imports",ids)
        self.assertIn("uncertainty:units",ids)
        self.assertEqual(parsed["context_revision"],g["context_revision"])
        self.assertTrue(parsed["omitted_context"]["count"]>0)
        self.assertTrue(len(payload)<=15000)

    def test_essential_obligation_that_cannot_fit_fails_closed(self):
        g=graph(extra_requirements=20)
        with patch.dict(os.environ,FLAGS,clear=True):
            with self.assertRaises(ContextBudgetExceeded):
                context_brief({"work_graph":g},specialist="excel",
                              max_chars=1500)

    def test_invalid_scope_and_corrupt_graph_do_not_get_summarized(self):
        g=graph()
        g["nodes"][0]["data"]["objective"]="tampered"
        with patch.dict(os.environ,FLAGS,clear=True):
            with self.assertRaises(ValueError):
                context_brief({"work_graph":g},specialist="excel",
                              max_chars=15000)


if __name__=="__main__":
    unittest.main()
