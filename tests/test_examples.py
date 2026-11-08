import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rizzler.artifacts import verify_artifact

ROOT=Path(__file__).resolve().parents[1]
EXAMPLES=ROOT/'examples'

class ExampleArtifactTests(unittest.TestCase):
    def test_sample_pdf(self):
        self.assertTrue(verify_artifact(EXAMPLES/'decision-intelligence.pdf','pdf').verified)
    def test_sample_docx(self):
        self.assertTrue(verify_artifact(EXAMPLES/'decision-intelligence.docx','docx').verified)
    def test_sample_pptx(self):
        self.assertTrue(verify_artifact(EXAMPLES/'decision-intelligence.pptx','pptx').verified)
    def test_sample_xlsx(self):
        self.assertTrue(verify_artifact(EXAMPLES/'decision-intelligence.xlsx','xlsx').verified)
    def test_sample_png(self):
        self.assertTrue(verify_artifact(EXAMPLES/'dataset-quality-example.png','png').verified)
