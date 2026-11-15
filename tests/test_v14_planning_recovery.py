"""Gemini planner-output recovery without optional test-framework dependencies."""
import asyncio
import importlib.util
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from rizzler.work_dynamic import generate, PlanningOutputError, _response_graph

PAYLOAD={"objective":"Prepare a supplier risk report",
         "deliverables":["pdf"],"uploads":[]}

def good_graph():
    return {"schema_version":2,"status":"ready","steps":[
        {"id":"orchestrator","tool":"orchestrator","depends_on":[],"thinking_level":"high"},
        {"id":"pdf_visual","tool":"pdf_visual","depends_on":["orchestrator"],"thinking_level":"medium"},
        {"id":"quality","tool":"quality","depends_on":["orchestrator","pdf_visual"],"thinking_level":"high"}]}

class FakeModels:
    def __init__(self,replies):
        self.replies=list(replies)
        self.configs=[]
    async def generate_content(self,*,model,contents,config):
        self.configs.append(config)
        return self.replies.pop(0)

class FakeClient:
    def __init__(self,replies):
        self.models=FakeModels(replies)
        self.aio=SimpleNamespace(models=self.models)

class PlannerRecoveryTests(unittest.TestCase):
    def test_strict_parser_rejects_extraneous_output(self):
        with self.assertRaises(ValueError):
            _response_graph(SimpleNamespace(parsed=None,text='{"a":1}{"b":2}'))

    def _sdk(self):
        if (importlib.util.find_spec("google") is None or
            importlib.util.find_spec("google.genai") is None):
            self.skipTest("Optional google-genai SDK not installed")

    def test_planner_repairs_malformed_response(self):
        self._sdk()
        bad=SimpleNamespace(text='{"bad": true}{"second": true}',parsed=None)
        valid=SimpleNamespace(text=json.dumps(good_graph()),parsed=None)
        client=FakeClient([bad,valid])
        settings=SimpleNamespace(gemini_api_key="",gemini_model="test-gemini",request_timeout=45)
        with patch("rizzler.work_dynamic.reserve_provider_call"):
            result=asyncio.run(generate(PAYLOAD,settings,client=client))
        self.assertEqual(result,good_graph())
        self.assertEqual(len(client.models.configs),2)
        for config in client.models.configs:
            self.assertEqual(config.response_mime_type,"application/json")
            self.assertEqual(config.response_json_schema["properties"]["steps"]["type"],"array")

    def test_planner_accepts_sdk_parsed_output(self):
        self._sdk()
        client=FakeClient([SimpleNamespace(text="INVALID",parsed=good_graph())])
        settings=SimpleNamespace(gemini_api_key="",gemini_model="test-gemini",request_timeout=45)
        with patch("rizzler.work_dynamic.reserve_provider_call"):
            result=asyncio.run(generate(PAYLOAD,settings,client=client))
        self.assertEqual(result,good_graph())

    def test_three_invalid_graphs_fail_closed(self):
        self._sdk()
        wrong=SimpleNamespace(text='[{"invalid":"not a graph"}]',parsed=None)
        client=FakeClient([wrong,wrong,wrong])
        settings=SimpleNamespace(gemini_api_key="",gemini_model="test-gemini",request_timeout=45)
        with patch("rizzler.work_dynamic.reserve_provider_call"):
            with self.assertRaises(PlanningOutputError):
                asyncio.run(generate(PAYLOAD,settings,client=client))
        self.assertEqual(len(client.models.configs),3)

if __name__=="__main__":
    unittest.main()
