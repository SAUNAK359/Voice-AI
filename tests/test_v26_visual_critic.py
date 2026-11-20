"""V26 real-pixel visual criticism contract and page-render integrity tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rizzler.work_visual_critic import (
    validate_visual_review,rasterized_pages,
    VisualReviewFailure,VisualReviewIncomplete)


class V26RenderedVisionContracts(unittest.TestCase):
    def test_valid_all_page_review_requires_every_submitted_page(self):
        verdict={"schema_version":2,"reviewed_pages":[1,2,3],
                 "decision":"pass","findings":[],
                 "summary":"Three real document pages have readable content and alignment."}
        self.assertEqual(validate_visual_review(verdict,pages=[1,2,3]),verdict)
        with self.assertRaises(VisualReviewIncomplete):
            validate_visual_review(verdict,pages=[1,2,3,4])

    def test_critical_visual_defect_cannot_be_approved(self):
        finding={"page":1,"category":"visual_overlap","severity":"high",
                 "evidence":"A rendered chart overlaps the slide title region.",
                 "repair":"Move the chart into an unobstructed bounded content zone."}
        verdict={"schema_version":2,"reviewed_pages":[1],
                 "decision":"pass","findings":[finding],
                 "summary":"A visual overlap must be repaired before publishing this slide."}
        with self.assertRaises(VisualReviewIncomplete):
            validate_visual_review(verdict,pages=[1])
        verdict["decision"]="revise"
        self.assertEqual(validate_visual_review(
            verdict,pages=[1])["decision"],"revise")

    def test_model_cannot_cite_a_page_not_in_actual_render(self):
        verdict={"schema_version":2,"reviewed_pages":[1],
                 "decision":"revise","findings":[{
                     "page":9,"category":"text_clipped","severity":"high",
                     "evidence":"The paragraph extends beyond the slide boundary.",
                     "repair":"Reduce copy and expand the text frame inside margins."}],
                 "summary":"A fake out-of-range page cannot become a repair target."}
        with self.assertRaises(VisualReviewIncomplete):
            validate_visual_review(verdict,pages=[1])

    @unittest.skipUnless(
        importlib.util.find_spec("fitz") is not None and
        importlib.util.find_spec("reportlab") is not None,
        "Requires full Work PDF render dependencies")
    def test_actual_pdf_pixels_are_rendered_not_inferred_from_metadata(self):
        from reportlab.pdfgen import canvas
        with TemporaryDirectory() as temp:
            path=Path(temp)/"test_document.pdf"
            pdf=canvas.Canvas(str(path),pagesize=(612,792))
            pdf.drawString(80,700,"Actual first page of a Rizzler report")
            pdf.showPage()
            pdf.drawString(80,700,"Actual second page with new evidence")
            pdf.save()
            pages=rasterized_pages(path,"pdf")
            self.assertEqual(len(pages),2)
            for item in pages:
                self.assertTrue(item["png"].startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertEqual(len(item["pixel_sha256"]),64)
            with self.assertRaises(VisualReviewIncomplete):
                rasterized_pages(path,"pdf",max_pages=1)


if __name__=="__main__":
    unittest.main()
