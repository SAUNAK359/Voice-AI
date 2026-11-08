import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rizzler.security import authenticate,new_session_id,safe_upload_name,scrub,validate_session_id

class SecurityTests(unittest.TestCase):
    def test_authenticate(self):
        self.assertTrue(authenticate('abc','abc'))
        self.assertFalse(authenticate('ab','abc'))
        self.assertFalse(authenticate(None,'abc'))
    def test_random_ids_are_distinct(self):
        self.assertNotEqual(new_session_id(),new_session_id())
    def test_name(self):
        self.assertEqual(safe_upload_name('test-data.xlsx'),'test-data.xlsx')
    def test_path_traversal(self):
        for name in ('../x.csv','../../var.csv','folder\\x.xlsx','report.py'):
            with self.subTest(name=name),self.assertRaises(ValueError):safe_upload_name(name)
    def test_redaction(self):
        self.assertNotIn('secret-value',scrub('key secret-value',('secret-value',)))
    def test_session_identifier(self):
        self.assertEqual(validate_session_id('valid_12'),'valid_12')
        with self.assertRaises(ValueError):validate_session_id('a/b')
