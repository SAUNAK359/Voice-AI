"""All Gemini Live tool declarations: strict request/negative-case matrix."""
import copy
import unittest
from rizzler.live_schema import DECLARATIONS,validate_call,public_schema

J="a"*32
GOOD={
"work_list":{},
"work_status":{"job_id":J},
"work_submit":{"objective":"Write the executive summary","deliverables":["md","pdf"],"source_coverage":"targeted"},
"source_search":{"query":"Where is the evidence?"},
"memory_recall":{"query":"Which currency should I use in reports?"},
"preview_open":{"job_id":J},
"preview_slide":{"job_id":J,"slide":1},
"preview_highlight":{"job_id":J,"text":"Performance"},
"preview_dashboard":{"job_id":J,"group_by":"Region","metric":"Count",
                     "chart":"bar","filter_column":"All","filter_value":""}
}
class LiveCallContractTests(unittest.TestCase):
    def test_all_declared_tools_are_covered(self):
        self.assertEqual(set(GOOD),{x["name"] for x in DECLARATIONS})
        for name in GOOD:
            self.assertEqual(validate_call(name,copy.deepcopy(GOOD[name])),GOOD[name])
            self.assertEqual(public_schema(name)["additionalProperties"],False)
    def test_missing_extra_and_wrong_types(self):
        for name,valid in GOOD.items():
            for bad in (None,False,3,[],{"unexpected":"x"},{**valid,"unexpected":1}):
                with self.subTest(name=name,bad=repr(bad)):
                    with self.assertRaises((ValueError,TypeError)):
                        validate_call(name,bad)
            for field in public_schema(name)["required"]:
                test=dict(valid);test.pop(field,None)
                with self.subTest(name=name,missing=field):
                    with self.assertRaises(ValueError):validate_call(name,test)
            for field,spec in public_schema(name)["properties"].items():
                bad=dict(valid)
                bad[field]=None
                with self.subTest(name=name,null=field):
                    with self.assertRaises(ValueError):validate_call(name,bad)
    def test_public_json_schema_matches_runtime_on_all_tools(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("Optional jsonschema library not installed")
        for name,valid in GOOD.items():
            schema=public_schema(name)
            Draft202012Validator.check_schema(schema)
            cases=[valid,None,True,0,[],"string",{**valid,"unknown":True}]
            for key,field in schema["properties"].items():
                for incorrect in (None,[],{},True,42," "):
                    sample=copy.deepcopy(valid)
                    sample[key]=incorrect
                    cases.append(sample)
                if field["type"]=="string":
                    for value in ("", " ", "  x  ", "a"*8001):
                        sample=copy.deepcopy(valid)
                        sample[key]=value
                        cases.append(sample)
            for test in cases:
                with self.subTest(tool=name,payload=repr(test)[:90]):
                    actual=Draft202012Validator(schema).is_valid(test)
                    try:
                        validate_call(name,test)
                        accepted=True
                    except (ValueError,TypeError):
                        accepted=False
                    self.assertEqual(actual,accepted)

    def test_semantic_boundaries(self):
        invalid=[
            ("work_status",{"job_id":"not-owned"}),
            ("source_search",{"query":""}),
            ("preview_slide",{"job_id":J,"slide":0}),
            ("preview_slide",{"job_id":J,"slide":501}),
            ("preview_slide",{"job_id":J,"slide":True}),
            ("preview_highlight",{"job_id":J,"text":"x"*161}),
            ("work_submit",{"objective":"X","deliverables":["md"],"source_coverage":"targeted"}),
            ("work_submit",{"objective":"Report","deliverables":[],"source_coverage":"targeted"}),
            ("work_submit",{"objective":"Report","deliverables":["pdf","pdf"],"source_coverage":"targeted"}),
            ("work_submit",{"objective":"Report","deliverables":["exe"],"source_coverage":"targeted"}),
            ("work_submit",{"objective":"Report","deliverables":["md"],"source_coverage":"both"}),
            ("preview_dashboard",{**GOOD["preview_dashboard"],"chart":"javascript"}),
            ("preview_dashboard",{**GOOD["preview_dashboard"],"filter_value":"x"*121})
        ]
        for name,bad in invalid:
            with self.subTest(name=name,bad=bad):
                with self.assertRaises(ValueError):validate_call(name,bad)
        with self.assertRaises(ValueError):validate_call("not_a_tool",{})
        with self.assertRaises(ValueError):validate_call("work_list",{},enabled=False)
if __name__=="__main__":unittest.main()
