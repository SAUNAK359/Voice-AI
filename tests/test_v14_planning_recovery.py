"""Gemini Work graph structured-output recovery, no template fallback."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
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

@pytest.mark.asyncio
async def test_planner_repairs_malformed_json_from_provider():
    broken=SimpleNamespace(text='{"bad": true}{"second": true}',parsed=None)
    valid=SimpleNamespace(text=json.dumps(good_graph()),parsed=None)
    client=FakeClient([broken,valid])
    settings=SimpleNamespace(gemini_api_key="",gemini_model="test-gemini",request_timeout=45)
    with patch("rizzler.work_dynamic.reserve_provider_call"):
        result=await generate(PAYLOAD,settings,client=client)
    assert result==good_graph()
    assert len(client.models.configs)==2
    for config in client.models.configs:
        assert config.response_mime_type=="application/json"
        assert config.response_json_schema["properties"]["steps"]["type"]=="array"

@pytest.mark.asyncio
async def test_planner_uses_sdk_parsed_output():
    item=SimpleNamespace(text="INVALID",parsed=good_graph())
    client=FakeClient([item])
    settings=SimpleNamespace(gemini_api_key="",gemini_model="test-gemini",request_timeout=45)
    with patch("rizzler.work_dynamic.reserve_provider_call"):
        assert await generate(PAYLOAD,settings,client=client)==good_graph()

@pytest.mark.asyncio
async def test_planner_rejects_three_invalid_graphs():
    wrong=SimpleNamespace(text='[{"invalid":"not a graph"}]',parsed=None)
    client=FakeClient([wrong,wrong,wrong])
    settings=SimpleNamespace(gemini_api_key="",gemini_model="test-gemini",request_timeout=45)
    with patch("rizzler.work_dynamic.reserve_provider_call"):
        with pytest.raises(PlanningOutputError):
            await generate(PAYLOAD,settings,client=client)
    assert len(client.models.configs)==3

def test_strict_parser_rejects_extraneous_model_output():
    with pytest.raises(ValueError):
        _response_graph(SimpleNamespace(parsed=None,text='{"a":1}{"b":2}'))
