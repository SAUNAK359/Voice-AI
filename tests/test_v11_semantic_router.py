"""V11.1 semantic routing regressions: offline provider fakes, no live claims."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from rizzler.cognitive_router import semantic_route
from rizzler.config import Settings
from rizzler.voice_tools import VoiceTools


class FakeSemantic:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error
        self.calls = 0
        self.aio = SimpleNamespace(models=self)

    async def generate_content(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return SimpleNamespace(text=json.dumps(self.value))


@pytest.fixture
def settings():
    return Settings(access_key="integration-test-secret-long-key-1234")


@pytest.mark.parametrize("utterance", [
    "Which Nifty stocks performed best today?",
    "Compare today's stock market performance with yesterday.",
    "How did the RBI decision affect Indian banking stocks this week?",
])
def test_paraphrased_fresh_information_routes_to_web(settings, utterance):
    fake = FakeSemantic({"intent": "web_search", "confidence": 0.95})
    decision = asyncio.run(semantic_route(utterance, settings, have_work=True,
                                          formats=[], client=fake))
    assert decision.intent == "web_search" and fake.calls == 1


@pytest.mark.parametrize("utterance", [
    "Explain the difference between NEFT and RTGS transactions.",
    "Can you hear me?",
])
def test_timeless_and_smalltalk_do_not_dispatch(settings, utterance):
    fake = FakeSemantic({"intent": "direct", "confidence": 0.98})
    decision = asyncio.run(semantic_route(utterance, settings, have_work=True,
                                          formats=[], client=fake))
    assert decision.intent is None


@pytest.mark.parametrize("value", [
    {"intent": "work_cancel", "confidence": 1.0},
    {"intent": "delete_all_files", "confidence": 1.0},
    {"intent": "web_search", "confidence": 0.5},
    {"intent": "web_search", "confidence": "high"},
    {"intent": "web_search", "confidence": True},
    {"intent": "web_search"},
    {"intent": "work_submit", "confidence": 1.0, "owner": "another_user"},
])
def test_invalid_and_unauthorized_intents_fail_closed(settings, value):
    fake = FakeSemantic(value)
    result = asyncio.run(semantic_route("Please do something", settings,
                                         have_work=True, formats=["pdf"], client=fake))
    assert result.intent is None


def test_model_cannot_turn_meta_question_into_private_write(settings):
    fake = FakeSemantic({"intent": "work_submit", "confidence": 0.99})
    for text in ("How do I create a PDF report?", "Why would someone build a spreadsheet?",
                 "Create a random file", "Make a report"):
        result = asyncio.run(semantic_route(text, settings, have_work=True,
                                             formats=[], client=fake))
        assert result.intent is None


def test_explicit_paraphrased_artifact_can_be_selected(settings):
    fake = FakeSemantic({"intent": "work_submit", "confidence": 0.95})
    result = asyncio.run(semantic_route("Put together an Excel workbook of expenses.",
                                         settings, have_work=True,
                                         formats=["xlsx"], client=fake))
    assert result.intent == "work_submit"


def test_provider_failure_does_not_trigger_action(settings):
    fake = FakeSemantic(error=TimeoutError("offline"))
    result = asyncio.run(semantic_route("Nifty gainers today?", settings,
                                         have_work=True, formats=[], client=fake))
    assert result.intent is None


def test_model_cannot_access_unavailable_work(settings):
    fake = FakeSemantic({"intent": "work_status", "confidence": 1.0})
    result = asyncio.run(semantic_route("Is my task complete?", settings,
                                         have_work=False, formats=[], client=fake))
    assert result.intent is None


def test_routing_respects_existing_permission_gateway(settings, monkeypatch):
    from rizzler import cognitive_router
    from rizzler.cognitive_router import SemanticDecision

    async def advise(*args, **kwargs):
        return SemanticDecision("web_search")

    async def fake_search(query, config):
        return {"text": "No valid current evidence", "spoken": "Unverified",
                "verified": False, "sources": []}

    monkeypatch.setattr(cognitive_router, "semantic_route", advise)
    import rizzler.voice_tools as tools
    monkeypatch.setattr(tools, "grounded_search", fake_search)
    result = asyncio.run(VoiceTools(None, settings).execute(
        "Which Nifty stocks performed best today?", "owner_123"))
    assert result["tool"] == "web_search" and result["verified"] is False
