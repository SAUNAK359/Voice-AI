"""Real raster preview smoke tests (offline, no LibreOffice needed for PDF)."""
import hashlib
import tempfile
import unittest
from pathlib import Path

class RenderedPreviewTests(unittest.TestCase):
    def test_pdf_pages_are_images_of_original_document(self):
        try:import fitz
        except ImportError:self.skipTest("PyMuPDF not installed")
        from rizzler.preview_pages import page_info,render_page
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"report.pdf"
            doc=fitz.open()
            p=doc.new_page(width=620,height=880)
            p.insert_text((60,80),"Quarterly evidence review")
            doc.save(path);doc.close()
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            info=page_info(d,"user_one",path,digest,"pdf")
            self.assertEqual(info["pages"],1)
            content=render_page(d,"user_one",path,digest,"pdf",1)
            self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertGreater(len(content),3000)
            with self.assertRaises(ValueError):
                render_page(d,"user_one",path,digest,"pdf",2)
    def test_unsupported_and_missing_renderers_rejected(self):
        from rizzler.preview_pages import source_pdf
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"file.txt";p.write_text("untrusted")
            with self.assertRaises(ValueError):
                source_pdf(d,"owner",p,"0"*64,"txt")
            with self.assertRaises(ValueError):
                source_pdf(d,"owner",Path(d)/"notfound.pdf","0"*64,"pdf")
    def test_visual_qa_option_is_explicit(self):
        from rizzler.work_visual import quality_mode
        from unittest.mock import patch
        for name in ("structural","strict","agentic"):
            with patch.dict("os.environ",{"RIZZLER_ARTIFACT_QA":name}):
                self.assertEqual(quality_mode(),name)
        with patch.dict("os.environ",{"RIZZLER_ARTIFACT_QA":"unknown"}):
            with self.assertRaises(ValueError):quality_mode()
if __name__=="__main__":unittest.main()
