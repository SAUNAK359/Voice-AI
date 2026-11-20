"""Proof-Carrying Context Fabric contracts: no missing caveats, forged proof
or owner leakage, plus source-sensitive dependent invalidation.
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_ir import compile_ir
from rizzler.work_context_fabric import (
    create_fabric,node,validate_fabric,migrate_v1,
    context_view,context_fetch,affected_dependents,
    ContextIntegrityError,ContextAccessDenied,ContextBudgetExceeded)


class ProofCarryingContextTests(unittest.TestCase):
    def setup_graph(self):
        ir=compile_ir("Data discussion",
            "# Data\nFour rows of synthetic values without real-world provenance.\n"
            "## Risks\nRegion and time cannot be separated in these observations.",
            ["https://docs.example.org/test"],{
                "rows":4,"sql_row_count":4,"numeric":{
                    "imports":{"count":4,"mean":150,"min":125,"max":175}}})
        return migrate_v1(ir,owner="tenant_1",job_id="job_123",
            objective="Create a synthetic analytical presentation",
            deliverables=["pptx"],requirements=[
                {"id":"g1","kind":"deliverable",
                 "obligation":"Deliver the requested PowerPoint",
                 "evidence_needed":"A valid editable slide deck","priority":5}],
            dataset_summary={"rows":4,"sql_row_count":4,
                             "numeric":{"imports":{
                               "count":4,"mean":150,"min":125,"max":175}}},
            unknowns=["No documented currency or measurement unit was supplied."])

    def test_v1_migration_never_certifies_report_text_as_verified_insight(self):
        graph=self.setup_graph()
        validate_fabric(graph)
        self.assertEqual(graph["schema_version"],2)
        narratives=[x for x in graph["nodes"] if x["kind"]=="narrative_candidate"]
        self.assertGreater(len(narratives),0)
        self.assertTrue(all(x["status"]=="candidate" for x in narratives))
        self.assertFalse(any(x["kind"]=="insight" for x in graph["nodes"]))
        self.assertTrue(any(x["kind"]=="metric" and
                            x["status"]=="computed_summary" for x in graph["nodes"]))

    def test_context_view_never_drops_critical_goal_or_caveat(self):
        graph=self.setup_graph()
        view=context_view(graph,owner="tenant_1",job_id="job_123",
                          specialist="powerpoint",max_bytes=8000)
        kinds={node_["kind"] for node_ in view["nodes"]}
        self.assertTrue({"goal","requirement","uncertainty"}<=kinds)
        self.assertEqual(view["context_revision"],graph["context_revision"])
        self.assertIn("omitted_context",view)

    def test_small_budget_fails_instead_of_silently_losing_caveat(self):
        graph=self.setup_graph()
        with self.assertRaises(ContextBudgetExceeded):
            context_view(graph,owner="tenant_1",job_id="job_123",
                         specialist="powerpoint",max_bytes=1000)

    def test_explicit_retrieval_is_owner_scoped_and_sha_verified(self):
        graph=self.setup_graph()
        response=context_fetch(
            graph,owner="tenant_1",job_id="job_123",
            specialist="excel",ids=["metric:0"],
            purpose="Independently check the source summary units",max_bytes=10000)
        ids={n["id"] for n in response["nodes"]}
        self.assertIn("metric:0",ids)
        self.assertIn("source:dataset",ids)
        with self.assertRaises(ContextAccessDenied):
            context_fetch(graph,owner="tenant_2",job_id="job_123",
                specialist="excel",ids=["metric:0"],
                purpose="Try to read another owner data",max_bytes=10000)

    def test_source_url_cannot_be_forged_as_verified_extraction(self):
        bad=node(id="source:url",kind="source",status="verified",
                 data={"url":"https://example.org","content_verified":False})
        with self.assertRaises(ContextIntegrityError):
            create_fabric(owner="tenant",job_id="job1",
                goal_digest="a"*64,nodes=[bad])

    def test_dependency_invalidation_is_transitive_but_not_global(self):
        goal=node(id="goal:a",kind="goal",data={"text":"actual goal"},status="approved")
        src=node(id="source:a",kind="source",data={"url":"https://x.test"},
                 status="attributed")
        fact=node(id="fact:a",kind="fact",data={"statement":"Hypothesis only"},
                  dependencies=("source:a",),status="candidate")
        insight=node(id="insight:a",kind="insight",data={"text":"Pending"},
                     dependencies=("fact:a",),status="candidate")
        other=node(id="fact:b",kind="fact",data={"text":"unrelated"},
                   dependencies=("goal:a",),status="candidate")
        graph=create_fabric(owner="tenant",job_id="job1",
            goal_digest="a"*64,nodes=[goal,src,fact,insight,other])
        self.assertEqual(
            affected_dependents(graph,{"source:a"}),["fact:a","insight:a"])

    def test_derived_math_receipts_survive_context_transfer_with_caveats(self):
        from rizzler.work_reasoning_audit import execute_comparison
        table=(["quarter","imports","exports","region"],[
            ["Q1","125","95","North"],["Q2","140","105","North"],
            ["Q3","160","117","South"],["Q4","175","133","South"]])
        plan={"schema_version":2,"category_column":"quarter",
              "first_measure":"imports","second_measure":"exports",
              "aggregation":"sum","measurement_unit":"unspecified_by_source",
              "analytical_question":"What was the difference across quarters?",
              "confounder_columns":["region"]}
        proof=execute_comparison(plan,table)
        ir=compile_ir("Data study",
            "# Findings\\nSynthetic data supports descriptive analysis.",
            [])
        graph=migrate_v1(ir,owner="tenant_1",job_id="job_123",
            objective="Analyze the synthetic data",deliverables=["pptx"],
            comparison_receipt=proof)
        view=context_view(graph,owner="tenant_1",job_id="job_123",
                          specialist="powerpoint",max_bytes=14000)
        nodes={x["id"]:x for x in view["nodes"]}
        self.assertEqual(nodes["metric:comparison_total_difference"]["data"]["value"],-150)
        self.assertTrue(any(x["kind"]=="uncertainty" for x in view["nodes"]))

    def test_large_optional_metrics_never_hide_hard_facts_or_caveats(self):
        from rizzler.work_reasoning_audit import execute_comparison
        headers=["period","first","second"]
        rows=[[str(i),str(i+5),str(i)] for i in range(90)]
        method={"schema_version":2,"category_column":"period",
                "first_measure":"first","second_measure":"second",
                "aggregation":"sum","measurement_unit":"unspecified_by_source",
                "analytical_question":"Compare two source series across observed periods.",
                "confounder_columns":[]}
        receipt=execute_comparison(method,(headers,rows))
        ir=compile_ir("Analysis",
            "# Observations\\nSynthetic observations require explicit uncertainty.",
            [])
        graph=migrate_v1(ir,owner="tenant_1",job_id="job_123",
            objective="Review the source evidence",deliverables=["pptx"],
            comparison_receipt=receipt)
        view=context_view(graph,owner="tenant_1",job_id="job_123",
                          specialist="powerpoint",max_bytes=11000)
        ids={node["id"] for node in view["nodes"]}
        self.assertIn("metric:comparison_total_difference",ids)
        self.assertIn("uncertainty:domain_method_0",ids)
        self.assertGreater(view["omitted_context"]["count"],0)
        expansion=context_fetch(
            graph,owner="tenant_1",job_id="job_123",
            specialist="powerpoint",ids=["metric:comparison_group_89"],
            purpose="Need the exact original quarterly differential",
            max_bytes=7000)
        self.assertIn("metric:comparison_group_89",
                      {node["id"] for node in expansion["nodes"]})

    def test_tampered_content_fails_canonical_digest_validation(self):
        graph=self.setup_graph()
        invalid=copy.deepcopy(graph)
        invalid["nodes"][0]["data"]["tamper"]=True
        with self.assertRaises(ContextIntegrityError):
            validate_fabric(invalid)

    def test_cyclic_dependencies_rejected(self):
        a=node(id="fact:a",kind="fact",data={},dependencies=("fact:b",))
        b=node(id="fact:b",kind="fact",data={},dependencies=("fact:a",))
        with self.assertRaises(ContextIntegrityError):
            create_fabric(owner="tenant",job_id="job1",
                goal_digest="b"*64,nodes=[a,b])


class DurableKnowledgeCheckpointTests(unittest.TestCase):
    def test_fenced_owner_scoped_replay_and_source_revision(self):
        from tempfile import TemporaryDirectory
        from rizzler.work_store import WorkStore,Missing
        with TemporaryDirectory() as root:
            store=WorkStore(root)
            job=store.submit(
                "tenant_1","Produce a source-grounded report",
                ["md"],"v26_knowledge_0001",[])
            worker="v26_worker"
            claim=store.claim(worker)
            self.assertEqual(claim["id"],job["id"])
            ir=compile_ir("Knowledge test",
                "# Findings\\nInitial source-dependent content is a narrative candidate.",
                [])
            first=migrate_v1(ir,owner="tenant_1",job_id=job["id"],
                objective="Produce a source-grounded report",deliverables=["md"])
            digest=store.save_knowledge_checkpoint(
                job["id"],worker,claim["fence"],first)
            self.assertEqual(len(digest),64)
            self.assertEqual(
                store.knowledge_checkpoint("tenant_1",job["id"]),first)
            with self.assertRaises(Missing):
                store.knowledge_checkpoint("tenant_2",job["id"])
            updated_ir=compile_ir("Knowledge test",
                "# Findings\\nCorrected source-dependent content is a narrative candidate.",
                [])
            revised=migrate_v1(updated_ir,owner="tenant_1",job_id=job["id"],
                objective="Produce a source-grounded report",deliverables=["md"])
            self.assertEqual(first["immutable_goal_digest"],
                             revised["immutable_goal_digest"])
            store.save_knowledge_checkpoint(
                job["id"],worker,claim["fence"],revised)
            self.assertNotEqual(first["context_revision"],
                                store.knowledge_checkpoint("tenant_1",job["id"])["context_revision"])
            unauthorized=migrate_v1(
                updated_ir,owner="tenant_1",job_id=job["id"],
                objective="Change the original requested scope",deliverables=["md"])
            with self.assertRaises(ValueError):
                store.save_knowledge_checkpoint(
                    job["id"],worker,claim["fence"],unauthorized)


if __name__=="__main__":
    unittest.main()
