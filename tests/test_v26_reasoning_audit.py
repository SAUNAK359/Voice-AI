"""V26 analytical verification: general source semantics and synthetic trade
P0 adversarial regressions from the production quality failure evidence.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rizzler.work_reasoning_audit import (
    MethodologyError,validate_comparison_plan,
    execute_comparison,verify_assertion)


ROWS=[
    ["Q1","125","95","North"],
    ["Q2","140","105","North"],
    ["Q3","160","117","South"],
    ["Q4","175","133","South"]]
TABLE=(["quarter","imports","exports","region"],ROWS)


def plan():
    return {"schema_version":2,"category_column":"quarter",
            "first_measure":"imports","second_measure":"exports",
            "aggregation":"sum",
            "measurement_unit":"unspecified_by_source",
            "analytical_question":"How does the trade balance vary by quarter?",
            "confounder_columns":["region"]}


class SourceBoundAnalyticalTests(unittest.TestCase):
    def test_independent_balance_oracle_rejects_uniform_claim(self):
        result=execute_comparison(plan(),TABLE)
        self.assertEqual(
            [g["difference"] for g in result["groups"]],
            ["-30","-35","-43","-42"])
        self.assertEqual(result["total_first"],"600")
        self.assertEqual(result["total_second"],"450")
        self.assertEqual(result["total_difference"],"-150")
        self.assertTrue(result["all_differences_negative"])
        self.assertFalse(result["uniform_differences"])
        self.assertTrue(verify_assertion(
            result,predicate="all_differences_negative")["supported"])
        self.assertFalse(verify_assertion(
            result,predicate="uniform_differences")["supported"])
        self.assertFalse(verify_assertion(
            result,predicate="net_total_equals",
            asserted_value=151)["supported"])
        self.assertTrue(verify_assertion(
            result,predicate="net_total_equals",
            asserted_value=-150)["supported"])

    def test_observed_region_time_confounding_cannot_prove_causation(self):
        result=execute_comparison(plan(),TABLE)
        self.assertFalse(
            result["confounder_diagnostics"]["region"][
                "observed_overlap_across_category"])
        self.assertFalse(verify_assertion(
            result,predicate="causal_effect_identified")["supported"])

    def test_no_invented_columns_or_relabelled_currency(self):
        invalid={**plan(),"second_measure":"invented_revenue"}
        with self.assertRaises(MethodologyError):
            validate_comparison_plan(invalid,TABLE)

    def test_bad_or_nonfinite_source_values_fail_closed(self):
        corrupted=(TABLE[0],[*ROWS[:2],["Q3","NaN","117","South"],ROWS[3]])
        with self.assertRaises(MethodologyError):
            execute_comparison(plan(),corrupted)

    def test_non_additive_plan_uses_documented_mean(self):
        table=(["sector","rate1","rate2"],[
            ["A","1.5","2.5"],["A","3.5","4.5"]])
        method={
            "schema_version":2,"category_column":"sector",
            "first_measure":"rate1","second_measure":"rate2",
            "aggregation":"mean",
            "measurement_unit":"percentage_points",
            "analytical_question":"What is the measured rate gap across sources?",
            "confounder_columns":[]}
        result=execute_comparison(method,table)
        self.assertEqual(result["groups"][0]["first"],"2.5")
        self.assertEqual(result["groups"][0]["difference"],"1.0")


if __name__=="__main__":
    unittest.main()
