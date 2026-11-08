import json
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class PublishedSchemaTests(unittest.TestCase):
    def test_example_matches_published_schema_structure(self):
        schema=json.loads((ROOT/'schemas/work-handoff-v1.json').read_text())
        example=json.loads((ROOT/'schemas/work-handoff-example.json').read_text())
        self.assertEqual(schema['$schema'],'https://json-schema.org/draft/2020-12/schema')
        self.assertTrue(set(schema['required']).issubset(example))
        self.assertTrue(set(example['deliverables']).issubset(schema['properties']['deliverables']['items']['enum']))
        self.assertFalse(example['permissions']['external_actions'])
        self.assertLessEqual(len(example['deliverables']),schema['properties']['deliverables']['maxItems'])
        self.assertLessEqual(example['constraints']['max_output_files'],schema['properties']['constraints']['properties']['max_output_files']['maximum'])
