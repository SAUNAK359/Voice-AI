import { describe, expect, it } from 'vitest';
import { executionGraph } from './graph';
import type { Agent, Plan } from './api';

const plan:Plan={
  status:'ready',
  steps:[
    {id:'research',tool:'research',depends_on:[],thinking_level:'high'},
    {id:'orchestrator',tool:'orchestrator',depends_on:['research'],thinking_level:'high'},
    {id:'powerpoint',tool:'powerpoint',depends_on:['orchestrator'],thinking_level:'medium'},
    {id:'quality',tool:'quality',depends_on:['research','orchestrator','powerpoint'],thinking_level:'high'}
  ]
};

describe('Rizzler V15 real DAG visualization',()=>{
  it('renders model-authored dependencies and actual agent statuses',()=>{
    const agents:Agent[]=[
      {agent:'research',status:'completed',attempt:2},
      {agent:'orchestrator',status:'running',attempt:1}
    ];
    const graph=executionGraph(plan,agents);
    expect(graph.nodes).toHaveLength(4);
    expect(graph.edges).toHaveLength(5);
    expect(graph.edges.find(x=>x.id==='research-orchestrator')).toBeTruthy();
    expect(graph.nodes.find(x=>x.id==='orchestrator')?.data.label).toContain('running');
    expect(graph.nodes.find(x=>x.id==='quality')?.data.label).toContain('queued');
  });
  it('shows no fake nodes or connections while planning',()=>{
    expect(executionGraph({status:'planning',steps:[]},[])).toEqual({nodes:[],edges:[]});
  });
  it('does not construct an edge to a missing specialist',()=>{
    const malformed:Plan={status:'ready',steps:[
      {id:'quality',tool:'quality',depends_on:['missing'],thinking_level:'high'}
    ]};
    expect(executionGraph(malformed,[]).edges).toEqual([]);
  });
});
