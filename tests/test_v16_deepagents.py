"""Offline boundary tests for the LangGraph/Deep Agents planner.

These tests never reach an external model, network, browser or local filesystem.
"""
import asyncio
import json
import sys
import types
import unittest
from unittest.mock import patch

from rizzler.work_deepagents import _safe_context, plan_with_deepagents, DeepAgentPlanningError


def candidate(with_sql=False):
    nodes = []
    if with_sql:
        nodes.append({"id": "sql_analytics", "tool": "sql_analytics", "depends_on": [], "thinking_level": "high"})
    nodes.append({"id": "research", "tool": "research", "depends_on": [], "thinking_level": "high"})
    nodes.append({"id": "orchestrator", "tool": "orchestrator",
                  "depends_on": ["research"] + (["sql_analytics"] if with_sql else []),
                  "thinking_level": "high"})
    nodes.append({"id": "powerpoint", "tool": "powerpoint", "depends_on": ["orchestrator"], "thinking_level": "medium"})
    nodes.append({"id": "quality", "tool": "quality",
                  "depends_on": [x["id"] for x in nodes], "thinking_level": "high"})
    return {"schema_version": 2, "status": "ready", "steps": nodes}


class PlannerContracts(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, initial):
        payload = {"objective": "Research recent Indian stock prices and make presentation",
                   "deliverables": ["research", "pptx"], "uploads": [],
                   "source_ids": [], "evidence_scope": "external_allowed"}
        outcomes = []

        def factory(*, model, tools, system_prompt, subagents):
            assert len(tools) == 2
            assert subagents and subagents[0]["name"] == "plan_reviewer"
            class Fake:
                async def ainvoke(self, values, config):
                    tools[0].invoke({})
                    for g in initial:
                        outcomes.append(tools[1].invoke({"graph_json": json.dumps(g)}))
                    return {"messages": []}
            return Fake()

        from rizzler.work_dynamic import WorkModelConfig
        result = await plan_with_deepagents(
            payload, WorkModelConfig("", "dummy-model", 45),
            model=object(), factory=factory)
        return result, outcomes

    async def test_rejected_dataset_hallucination_then_valid_replan(self):
        def illegal():
            x=candidate(with_sql=True)
            x["steps"][1]["depends_on"]=[]
            return x
        graph, outcomes = await self.invoke([illegal(), candidate()])
        self.assertEqual(graph["steps"][0]["id"], "research")
        self.assertIn("rejected:", outcomes[0])
        self.assertIn("accepted:", outcomes[1])

    async def test_fails_closed_if_no_graph_submitted(self):
        payload = {"objective": "Create a research presentation", "deliverables": ["research", "pptx"], "uploads": []}
        def factory(**kwargs):
            class Fake:
                async def ainvoke(self, values, config):
                    return {"messages": []}
            return Fake()
        from rizzler.work_dynamic import WorkModelConfig
        with self.assertRaisesRegex(DeepAgentPlanningError, "no_valid_graph"):
            await plan_with_deepagents(payload, WorkModelConfig("", "dummy", 45), model=object(), factory=factory)

    def test_context_never_includes_storage_or_owner(self):
        data={"objective": "Create a report", "deliverables": ["pptx"],
              "uploads": ["private_file_001"], "owner": "private_owner",
              "secret": "do_not_share"}
        values = _safe_context(data)
        self.assertEqual(values["dataset_attached"], True)
        self.assertNotIn("owner", values)
        self.assertNotIn("secret", json.dumps(values))
        self.assertNotIn("private_file_001", json.dumps(values))
