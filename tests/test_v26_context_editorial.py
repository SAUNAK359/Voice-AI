"""V26 PCCF and editorial: migration, trust, authorization and no silent loss."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_context_fabric import (
    digest,new_graph,validate_graph,validate_node,commit_nodes,
    select_context,verify_context_packet)
from rizzler.work_context_adapter import legacy_context_to_fabric
from rizzler.work_readiness import (
    requirement_phase,phase_aware_coverage,evidence_readiness)
from rizzler.work_editorial_director import (
    validate_editorial_plan,project_selected_ir,
    restore_original_section_ids)
from rizzler.work_studio import validate_storyboard
from rizzler.work_ir import compile_ir
from rizzler.work_context_intelligence import (
    validate_context_review,snapshot_context)


def node(kind,id_,*,text="Verified source data is available",
         status="unknown",critical=False,refs=None,unit=""):
    return {
        "id":kind+":"+id_,"kind":kind,"status":status,
        "statement":text,"source_ids":refs or [],"unit":unit,
        "scope":{},"critical":critical,"audience_tags":[],"digest":None}


class ProofCarryingFabricTests(unittest.TestCase):
    def setUp(self):
        self.task={"objective":"Produce an evidence-backed review",
                   "deliverables":["pptx","docx"]}
        self.base=new_graph(owner="owner1",job_id="job1",task=self.task)

    def test_versioned_commit_and_tenant_bound_selection(self):
        graph=commit_nodes(self.base,owner="owner1",job_id="job1",
            base_revision=self.base["revision"],
            nodes=[node("goal","original",critical=True),
                   node("uncertainty","limited",text=(
                       "The supplied measurements do not identify a reporting unit."),
                       critical=True)])
        packet=select_context(graph,owner="owner1",job_id="job1",
            recipient="powerpoint",required_ids=["goal:original"],
            byte_budget=4500)
        self.assertTrue(packet["completeness"]["mandatory_included"])
        self.assertEqual(set(packet["required_ids"]),
                         {"goal:original","uncertainty:limited"})
        verify_context_packet(packet,owner="owner1",job_id="job1",
                              recipient="powerpoint",revision=graph["revision"])
        with self.assertRaises(PermissionError):
            select_context(graph,owner="other",job_id="job1",
                           recipient="powerpoint",required_ids=[])

    def test_old_context_revision_is_rejected(self):
        initial=commit_nodes(self.base,owner="owner1",job_id="job1",
            base_revision=self.base["revision"],
            nodes=[node("goal","original")])
        with self.assertRaises(PermissionError):
            commit_nodes(initial,owner="owner1",job_id="job1",
                         base_revision=self.base["revision"],
                         nodes=[node("fact","other")])

    def test_no_silent_truncation_of_mandatory_caveat(self):
        extremely_long="Evidence limitation "+("critical caveat "*190)
        graph=commit_nodes(self.base,owner="owner1",job_id="job1",
            base_revision=self.base["revision"],
            nodes=[node("goal","original",critical=True),
                   node("uncertainty","scope",text=extremely_long,critical=True)])
        with self.assertRaises(ValueError):
            select_context(graph,owner="owner1",job_id="job1",
                           recipient="powerpoint",
                           required_ids=["goal:original"],
                           byte_budget=1500)

    def test_unverified_provider_url_does_not_upgrade_to_proof(self):
        untrusted=node("source","link",text="https://example.org/report",
                       status="provider_attributed")
        self.assertEqual(validate_node(untrusted)["status"],
                         "provider_attributed")
        claimed=node("fact","verified",text="The market grew by 30%.",
                     status="source_verified",refs=["source:link"])
        with self.assertRaises(ValueError):
            validate_node(claimed)
        measured=node("metric","imports",text="Imports = 600",
                      status="computed_verified",refs=["source:dataset_digest"],
                      unit="unspecified_source_unit")
        self.assertEqual(validate_node(measured)["status"],"computed_verified")

    def test_legacy_adapter_avoids_fake_research_evidence(self):
        ir=compile_ir(
            "Synthetic trade research","# Findings\nFour observations only.",
            ["https://example.org/official"],
            {"rows":4,"sql_row_count":4,
             "numeric":{"imports":{"count":4,"min":125,
                                    "max":175,"mean":150.0}}})
        result=legacy_context_to_fabric(
            owner="tenant1",job_id="job1",
            payload={"objective":"Analyze the source synthetic data",
                     "deliverables":["pptx"]},ir=ir,
            summary={"rows":4,"sql_row_count":4,
                     "numeric":{"imports":{"count":4,"min":125,
                                           "max":175,"mean":150.0}}},
            goal_contract=None)
        self.assertEqual(result["schema_version"],2)
        self.assertTrue(any(x["kind"]=="metric" for x in result["nodes"]))
        urls=[x for x in result["nodes"] if x["kind"]=="source"]
        self.assertEqual(urls[0]["status"],"provider_attributed")
        self.assertTrue(any(x["kind"]=="uncertainty"
                            and x["critical"] for x in result["nodes"]))


class PhaseAwareReadinessTests(unittest.TestCase):
    def test_future_artifacts_not_missing_source_evidence(self):
        requirements=[
            {"id":"g1","kind":"evidence"},{"id":"g2","kind":"deliverable"},
            {"id":"g3","kind":"quality"}]
        input_coverage=[
            {"id":"g1","status":"supported","evidence_refs":[]},
            {"id":"g2","status":"unknown","evidence_refs":[]},
            {"id":"g3","status":"partial","evidence_refs":[]}]
        upgraded=phase_aware_coverage(input_coverage,requirements)
        self.assertEqual([x["status"] for x in upgraded],
                         ["supported","execution_pending","execution_pending"])
        self.assertTrue(evidence_readiness(upgraded,requirements))
        self.assertEqual(input_coverage[1]["status"],"unknown")

    def test_missing_analytic_evidence_stays_blocking(self):
        requirements=[
            {"id":"g1","kind":"analysis"},{"id":"g2","kind":"deliverable"}]
        coverage=[
            {"id":"g1","status":"unknown","evidence_refs":[]},
            {"id":"g2","status":"unknown","evidence_refs":[]}]
        self.assertFalse(evidence_readiness(
            phase_aware_coverage(coverage,requirements),requirements))

    def test_integration_fabric_and_phase_flags_are_off_by_default(self):
        from rizzler.v23_flags import enabled
        with patch.dict("os.environ",{"RIZZLER_V23_MODE":"full"},clear=True):
            self.assertFalse(enabled("RIZZLER_V26_CONTEXT_FABRIC"))
            self.assertFalse(enabled("RIZZLER_V26_OUTCOME_PHASES"))

    def test_context_supervisor_can_be_ready_before_rendered_binary_exists(self):
        ir=compile_ir(
            "Synthetic inputs","# Evidence\nThe original data is available.",
            ["https://example.org/report"])
        reqs=[
            {"id":"g1","kind":"evidence",
             "obligation":"Explain verified findings"},
            {"id":"g2","kind":"deliverable",
             "obligation":"Produce a PowerPoint file"}]
        package=snapshot_context(
            {"objective":"Present verified source findings",
             "deliverables":["research","pptx"],"uploads":[]},
            {"artifact_ir":ir,
             "goal_contract":{"requirements":reqs,"unknowns":[]}},
            focus=("powerpoint",))
        proposal={"schema_version":1,"decision":"ready",
            "coverage":[
                {"id":"g1","status":"supported",
                 "evidence_refs":["https://example.org/report"]},
                {"id":"g2","status":"unknown","evidence_refs":[]}],
            "requests":[],
            "assessment":"Original research is sufficient to begin rendering."}
        with patch.dict("os.environ",{
                "RIZZLER_V23_MODE":"full",
                "RIZZLER_V26_OUTCOME_PHASES":"1"},clear=True):
            ready=validate_context_review(
                proposal,package=package,permitted=frozenset({"research"}))
        self.assertEqual(ready["decision"],"ready")
        self.assertEqual(ready["coverage"][1]["status"],"execution_pending")


class V26EditorialTests(unittest.TestCase):
    def setUp(self):
        self.ir=compile_ir(
            "Investor briefing",
            "# Decision summary\nThe source records an important result.\n"
            "## SQL Execution Log\nThe database ran three safe query operations.\n"
            "## Analysis\nThe final interpretation includes a material limitation.",
            ["https://example.org/verified"])
        self.plan={
            "schema_version":1,"audience":"executive decision makers",
            "thesis":"The results support only a bounded interpretation from the source.",
            "selected_section_ids":[0,2],
            "excluded_section_ids":[1],
            "goal_coverage":[
                {"goal_id":"g1","section_ids":[0,2],
                 "reason":"These sections cover the conclusion and limits."}],
            "caveats":["The source observations are insufficient for a forecast."],
            "rationale":"Exclude implementation logs because the user requested an executive analysis."}

    def test_irrelevant_implementation_notes_excluded_from_slide_source(self):
        self.assertEqual(validate_editorial_plan(
            self.plan,section_count=3,required_goals=["g1"]),self.plan)
        local=project_selected_ir(self.ir,self.plan)
        self.assertEqual(len(local.sections),2)
        self.assertNotIn("SQL Execution Log",str(local.sections))
        self.assertEqual(len(self.ir.sections),3)

    def test_editorial_plan_cannot_drop_all_evidence(self):
        bad={**self.plan,"selected_section_ids":[]}
        with self.assertRaises(ValueError):
            validate_editorial_plan(
                bad,section_count=3,required_goals=["g1"])

    def test_editorial_source_map_cannot_invent_new_sections(self):
        local={
            "schema_version":1,
            "slides":[{"title":"A meaningful finding","message":
                "The result is bounded by the original source limitations.",
                "kind":"takeaway",
                "bullets":["The source records an important result.",
                           "The conclusion has a material limitation."],
                "section_ids":[0,1],
                "source_urls":["https://example.org/verified"]}] * 3}
        mapped=restore_original_section_ids(local,self.plan)
        self.assertEqual(mapped["sections_covered"],[0,2])
        accepted=validate_storyboard(
            mapped,self.ir.sections,self.ir.sources,
            required_section_ids=frozenset({0,2}))
        self.assertEqual(accepted["sections_covered"],[0,2])
        with self.assertRaises(ValueError):
            validate_storyboard(mapped,self.ir.sections,self.ir.sources)


if __name__=="__main__":
    unittest.main()
