"""Fail-closed factual lineage in source-driven table extraction."""
import unittest
from rizzler.work_structured_research import as_table,validate

URL="https://example.com/source"
PASSAGES=[{"url":URL,"excerpt":"On Nov 17 the closing price was 125.40 and volume 4500 shares."}]

class ExtractTests(unittest.TestCase):
    def record(self,value="125.40",quote="On Nov 17 the closing price was 125.40 and volume 4500 shares."):
        return {"columns":["Closing"],"rows":[{
            "cells":[value],"source_url":URL,"quote":quote}]}

    def test_accept_directly_quoted_numeric_cell(self):
        value=validate(self.record(),PASSAGES)
        self.assertEqual(as_table(value),(["Closing","Source URL"],[["125.40",URL]]))

    def test_refuse_invented_market_price(self):
        with self.assertRaisesRegex(ValueError,"source passage"):
            validate(self.record(value="999.99"),PASSAGES)

    def test_refuse_invented_date_or_label(self):
        with self.assertRaisesRegex(ValueError,"source passage"):
            validate(self.record(value="2026-12-31"),PASSAGES)

    def test_refuse_fake_source_or_fake_quote(self):
        with self.assertRaisesRegex(ValueError,"source passage"):
            validate(self.record(quote="The market increased hugely."),PASSAGES)
        bogus=self.record();bogus["rows"][0]["source_url"]="https://wrong.example.net/"
        with self.assertRaisesRegex(ValueError,"source passage"):
            validate(bogus,PASSAGES)

    def test_reject_partial_numeric_token(self):
        with self.assertRaisesRegex(ValueError,"Numerical cell"):
            validate(self.record(value="25"),PASSAGES)
