"""LangGraph execution waves are driven by an LLM-authored DAG."""
import asyncio
import importlib.util
import unittest

from rizzler.work_graph_exec import execute_dependency_graph


@unittest.skipUnless(importlib.util.find_spec("langgraph") is not None,
                     "Deep Agents/LangGraph optional extra is not installed")
class WorkGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_model_selected_waves(self):
        graph={"steps":[
            {"id":"research","depends_on":[]},
            {"id":"sql_analytics","depends_on":[]},
            {"id":"orchestrator","depends_on":["research","sql_analytics"]},
            {"id":"powerpoint","depends_on":["orchestrator"]},
            {"id":"word","depends_on":["orchestrator"]},
            {"id":"quality","depends_on":["research","sql_analytics","orchestrator","powerpoint","word"]},
        ]}
        waves=[]
        async def runner(names):
            waves.append(names)
        result=await execute_dependency_graph(graph,runner)
        self.assertEqual(waves,[
            ["research","sql_analytics"],
            ["orchestrator"],["powerpoint","word"],["quality"]])
        self.assertEqual(set(result),{n["id"] for n in graph["steps"]})

    async def test_no_success_after_failed_specialist_wave(self):
        graph={"steps":[
            {"id":"research","depends_on":[]},
            {"id":"powerpoint","depends_on":["research"]},
            {"id":"quality","depends_on":["research","powerpoint"]},
        ]}
        invoked=[]
        async def runner(nodes):
            invoked.append(nodes)
            raise RuntimeError("research_source_unavailable")
        with self.assertRaisesRegex(RuntimeError,"research_source_unavailable"):
            await execute_dependency_graph(graph,runner)
        self.assertEqual(invoked,[["research"]])

    async def test_corrupt_or_cycle_graph_fails_closed(self):
        async def noop(nodes):
            raise AssertionError("unvalidated tools must never execute")
        with self.assertRaises(ValueError):
            await execute_dependency_graph({"steps":[
                {"id":"a","depends_on":["b"]},{"id":"b","depends_on":["a"]}
            ]},noop)
