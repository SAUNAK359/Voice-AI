"""Adaptive SQL investigator: source bounds, genuine analytics and security."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rizzler.work_sql_exploration import (
    SQLResearchSandbox, dataset_intelligence,
    validate_investigation_plan, validate_analyst_synthesis,
    render_analysis_brief,
)


class AdaptiveSQLTests(unittest.TestCase):
    def setUp(self):
        self.header=["year","region","imports_usd","exports_usd"]
        self.rows=[
            ["2023","East","100","70"],
            ["2023","West","200","190"],
            ["2024","East","120","130"],
            ["2024","West","250","180"],
        ]

    def test_understands_numeric_fields_and_distributions(self):
        profile=dataset_intelligence(self.header,self.rows)
        self.assertEqual(profile["row_count"],4)
        fields={f["name"]:f for f in profile["fields"]}
        self.assertEqual(fields["imports_usd"]["distribution"]["median"],160)
        self.assertEqual(fields["year"]["type_hint"],"numeric")
        self.assertEqual(fields["region"]["type_hint"],"categorical_or_text")
        self.assertEqual(fields["region"]["distinct"],2)

    def test_actual_grouped_sql_market_deficit(self):
        engine=SQLResearchSandbox(self.header,self.rows)
        try:
            result=engine.query(
                "SELECT c0 AS year, SUM(CAST(c2 AS REAL)) AS imports, "
                "SUM(CAST(c3 AS REAL)) AS exports, "
                "SUM(CAST(c3 AS REAL)-CAST(c2 AS REAL)) AS net_trade "
                "FROM dataset GROUP BY c0 ORDER BY c0")
            self.assertEqual(result["rows"],[
                ["2023",300.0,260.0,-40.0],
                ["2024",370.0,310.0,-60.0]])
            comparative=engine.query(
                "SELECT c1 AS region, SUM(CAST(c3 AS REAL)) AS exports, "
                "ROUND(100.0*SUM(CAST(c3 AS REAL))/"
                "(SELECT SUM(CAST(c3 AS REAL)) FROM dataset),2) AS share_pct "
                "FROM dataset GROUP BY c1 ORDER BY exports DESC")
            self.assertAlmostEqual(comparative["rows"][0][2],64.91,places=2)
        finally:
            engine.close()

    def test_sql_sandbox_blocks_mutation_attach_pragmas_and_writes(self):
        engine=SQLResearchSandbox(self.header,self.rows)
        try:
            for query in (
                "DELETE FROM dataset",
                "SELECT * FROM dataset; DROP TABLE dataset",
                "SELECT load_extension('bad') FROM dataset",
                "WITH x AS (DELETE FROM dataset RETURNING *) SELECT * FROM x",
                "SELECT * FROM sqlite_master",
                "PRAGMA table_info(dataset)",
                "SELECT * FROM dataset -- bypass"
            ):
                with self.subTest(query=query),self.assertRaises(
                        (ValueError,sqlite3.Error,PermissionError)):
                    engine.query(query)
        finally:
            engine.close()

    def test_query_result_cap_prevents_raw_row_dump(self):
        engine=SQLResearchSandbox(["a"],[[str(i)] for i in range(80)])
        try:
            with self.assertRaises(ValueError):
                engine.query("SELECT c0 FROM dataset")
        finally:
            engine.close()

    def test_investigation_contract_refuses_invented_authority(self):
        valid={"schema_version":1,"queries":[{
            "id":"trade1","question":"How did the yearly trade balance change?",
            "sql":"SELECT c0, SUM(CAST(c3 AS REAL)-CAST(c2 AS REAL)) "
                  "FROM dataset GROUP BY c0",
            "rationale":"Compare actual year-level import and export balances."}],
            "next_gaps":["Check uncertainty around reporting periods"]}
        plan=validate_investigation_plan(valid)
        self.assertEqual(len(plan["queries"]),1)
        with self.assertRaises(ValueError):
            validate_investigation_plan(valid,{"trade1"})
        for bad_sql in ("DROP TABLE dataset", "SELECT * FROM dataset; UPDATE dataset",
                        "SELECT c0 FROM dataset -- injected"):
            document={**valid,"queries":[{**valid["queries"][0],"sql":bad_sql}]}
            with self.subTest(sql=bad_sql),self.assertRaises(ValueError):
                validate_investigation_plan(document)

    def test_synthesis_references_executed_sql_receipts_only(self):
        queries=[{"id":"trade1","status":"ok"}]
        valid={"schema_version":1,"insights":[{
            "finding":"Exports did not exceed imports over the comparison window.",
            "evidence_ids":["trade1"],"caveat":"Data covers only uploaded rows."}],
            "unresolved":["Check full national customs data"],
            "next_actions":["Corroborate with original published statistics"]}
        self.assertEqual(len(validate_analyst_synthesis(valid,queries)["insights"]),1)
        with self.assertRaises(ValueError):
            validate_analyst_synthesis(
                {**valid,"insights":[{**valid["insights"][0],"evidence_ids":["fake"]}]},
                queries)

    def test_analysis_brief_contains_experiments_and_caveats(self):
        profile=dataset_intelligence(self.header,self.rows)
        q={"id":"trade1","question":"Actual trade balance by year",
           "rationale":"Check deficit trend in uploaded rows",
           "sql":"SELECT c0, SUM(CAST(c3 AS REAL)-CAST(c2 AS REAL)) FROM dataset GROUP BY c0",
           "status":"ok","result":{
               "columns":["year","net"],"rows":[["2023",-40],["2024",-60]],"count":2}}
        summary=render_analysis_brief(profile,[q],None)
        self.assertIn("2024",summary)
        self.assertIn("Actual trade balance",summary)
        self.assertIn("-60",summary)


if __name__=="__main__":
    unittest.main()
