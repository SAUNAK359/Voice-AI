import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from validate_notebook import validate

class NotebookTests(unittest.TestCase):
    def test_notebook_contract_and_order(self):
        self.assertGreater(validate()['python_cells'],20)
