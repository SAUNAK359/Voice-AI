"""Strict research relevance, ranking and partial claim recovery tests."""
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rizzler.research_intelligence import (
    validate_source_order, salvage_verified_claims, validate_focus)
from rizzler.evidence_graph import evidence_brief


def _source(identity, url):
    return {"id":identity,"url":url,"title":identity,
            "publisher":"vertexaisearch.cloud.google.com",
            "attribution":"provider_grounding","content_verified":False}


def _passage(identity, label, body):
    return {identity: {
        "source_id":label,"source_url":"https://example.org/"+label,
        "source_sha256":"a"*64,"location":{"page":1},
        "passage_sha256":hashlib.sha256(body.encode()).hexdigest(),
        "text":body}}


class ResearchIntelligenceContracts(unittest.TestCase):
    def test_model_can_reorder_not_invent_or_drop_sources(self):
        records=[_source("a","https://example.org/a"),
                 _source("b","https://example.org/b")]
        chosen=validate_source_order({"ranked_ids":["b","a"]},records)
        self.assertEqual([x["id"] for x in chosen],["b","a"])
        for sequence in (["a","unknown"],["b","b"],["a"],["a","b","extra"]):
            with self.subTest(sequence=sequence),self.assertRaises(ValueError):
                validate_source_order({"ranked_ids":sequence},records)
        with self.assertRaises(ValueError):
            validate_source_order({"ranked_ids":["b","a"],"hack":True},records)

    def test_salvages_good_quote_without_admitting_fabricated_citation(self):
        snippet=(
            "Merchandise export value in the recorded period is 123 units "
            "and imports total 156 units according to the source table.")
        spans=_passage("valid_eid_001","official",snippet)
        valid={
            "claim":"Exports were 123 units during the recorded period.",
            "evidence_id":"valid_eid_001",
            "quote":"Merchandise export value in the recorded period is 123 units",
            "interpretation":False,"limitations":"The period must be confirmed."}
        bad=dict(valid,evidence_id="fake_eid")
        document={"schema_version":1,"claims":[bad,valid]}
        accepted,rejections=salvage_verified_claims(document,spans)
        self.assertEqual(len(accepted),1)
        self.assertEqual(accepted[0]["source_url"],"https://example.org/official")
        self.assertEqual(sum(rejections.values()),1)
        self.assertEqual(accepted[0]["status"],"quoted_source_observation")

    def test_false_quote_and_duplicate_are_not_salvaged(self):
        spans=_passage("e1","gov",
            "The original dataset contains 19 measured observations.")
        claim={"claim":"Original dataset contains 19 observations.",
               "evidence_id":"e1","quote":"The original dataset contains 19",
               "interpretation":False,"limitations":""}
        fake=dict(claim,quote="The original dataset contains 99")
        valid,rejected=salvage_verified_claims(
            {"schema_version":1,"claims":[claim,fake,claim]},spans)
        self.assertEqual(len(valid),1)
        self.assertEqual(sum(rejected.values()),2)

    def test_focus_cannot_approve_unknown_claim_or_empty_answer(self):
        claims=[{"id":"x","claim":"The original monthly export figure is 12 units."}]
        good={"answers_question":True,"selected_ids":["x"],
              "missing_aspects":[]}
        self.assertEqual(validate_focus(good,claims)["selected_ids"],["x"])
        for bad in (
            dict(good,selected_ids=["invented"]),
            dict(good,selected_ids=[]),
            dict(good,selected_ids=["x","x"]),
            dict(good,missing_aspects=[""]),
            dict(good,answers_question="yes"),
        ):
            with self.subTest(case=bad),self.assertRaises(ValueError):
                validate_focus(bad,claims)
        not_answered={"answers_question":False,"selected_ids":[],
                      "missing_aspects":["Official figures for both periods"]}
        self.assertFalse(validate_focus(not_answered,claims)["answers_question"])

    def test_passage_prompt_does_not_exclude_secondary_primary_source(self):
        spans={}
        for index in range(18):
            spans.update(_passage("a"+str(index),"tutorial",
                "The tutorial describes agency responsibilities and "
                "general historical research instructions."*4))
        spans.update(_passage("officialfigure","statistics",
            "The original official export table reports actual numerical "
            "merchandise exports and imports in billions for both years."))
        brief=evidence_brief(spans,max_chars=2800)
        self.assertIn("officialfigure",brief)
        self.assertIn("statistics",brief)

if __name__=="__main__":
    unittest.main()
