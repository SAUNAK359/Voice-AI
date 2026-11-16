"""Model-authored specialist DAG execution using LangGraph.

Graph node decisions are *not* keyword routes. A validated LLM DAG determines
all enabled capabilities and dependency ordering. The bounded wave scheduler
only applies dependency/safety constraints. WorkStore remains the single
authority for owned job status, fenced execution, per-stage checkpoints and
final publication; LangGraph is not a competing persistent job queue.

A restarted worker reconstructs this graph from the immutable committed DAG,
and each specialist reuses only valid WorkStore checkpoints. LangGraph nodes
must not publish directly or bypass owner checks.
"""
from __future__ import annotations

from typing import TypedDict, Awaitable, Callable


class WaveState(TypedDict):
    pending: list[str]
    completed: list[str]


async def execute_dependency_graph(
    graph: dict,
    run_wave: Callable[[list[str]], Awaitable[None]],
) -> list[str]:
    from langgraph.graph import StateGraph, START, END

    steps=graph["steps"]
    nodes={node["id"]:frozenset(node["depends_on"]) for node in steps}
    order=[node["id"] for node in steps]
    if len(nodes)!=len(order) or not order or any(
            not deps.issubset(nodes) for deps in nodes.values()):
        raise ValueError("Invalid committed Work DAG")
    # Validate ordering locally as defense against an altered plan checkpoint.
    observed=set()
    for name in order:
        if not nodes[name].issubset(observed):
            raise ValueError("Work DAG is not topologically ordered")
        observed.add(name)

    async def run_ready(state: WaveState) -> WaveState:
        completed=set(state["completed"])
        pending=set(state["pending"])
        ready=[name for name in order
               if name in pending and nodes[name].issubset(completed)]
        if not ready:
            raise ValueError("Work DAG cannot advance")
        await run_wave(ready)
        completed.update(ready)
        pending.difference_update(ready)
        return {
            "completed":[name for name in order if name in completed],
            "pending":[name for name in order if name in pending],
        }

    def next_wave(state: WaveState):
        return END if not state["pending"] else "execute_ready"

    builder=StateGraph(WaveState)
    builder.add_node("execute_ready",run_ready)
    builder.add_edge(START,"execute_ready")
    builder.add_conditional_edges("execute_ready",next_wave)
    result=await builder.compile().ainvoke(
        {"pending":order,"completed":[]},
        config={"recursion_limit":max(12,2*len(order)+4)},
    )
    if result["pending"] or set(result["completed"])!=set(nodes):
        raise RuntimeError("LangGraph execution did not finish its approved DAG")
    return result["completed"]
