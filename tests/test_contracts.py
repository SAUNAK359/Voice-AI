import hashlib
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rizzler.contracts import Handoff,ArtifactReceipt,completion_gate

class ContractTests(unittest.TestCase):
    def test_handoff_valid(self):
        h=Handoff('session_123','Make executive report',('pdf','pptx'))
        self.assertIs(h.validate(),h)
    def test_handoff_unexpected_action_forbidden(self):
        with self.assertRaises(PermissionError):Handoff('session_123','Send email now',('pdf',),external_actions=True).validate()
    def test_handoff_unknown_format(self):
        with self.assertRaises(ValueError):Handoff('session_123','Make movie please',('exe',)).validate()
    def test_handoff_duplicates(self):
        with self.assertRaises(ValueError):Handoff('session_123','Make two PDFs',('pdf','pdf')).validate()
    def test_handoff_bad_session(self):
        with self.assertRaises(ValueError):Handoff('../escape','Make report now',('pdf',)).validate()
    def test_missing_required_artifact_is_not_complete(self):
        h=Handoff('session_123','Make a presentation',('pptx','pdf'))
        receipt=ArtifactReceipt('pptx','test.pptx',hashlib.sha256(b'slide').hexdigest(),5,True)
        with self.assertRaises(ValueError):completion_gate(h,[receipt],'completed')
    def test_broken_receipt_rejected(self):
        with self.assertRaises(ValueError):ArtifactReceipt('pdf','x.pdf','bad',100,True).validate()
    def test_completed_requires_outcome(self):
        h=Handoff('session_123','Make a PDF report',('pdf',))
        self.assertFalse(completion_gate(h,[],'failed'))
    def test_verified_artifact_completes(self):
        h=Handoff('session_123','Make a PDF report',('pdf',))
        r=ArtifactReceipt('pdf','x.pdf',hashlib.sha256(b'a').hexdigest(),1,True)
        self.assertTrue(completion_gate(h,[r],'completed'))
