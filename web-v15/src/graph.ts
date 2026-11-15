import type { Node, Edge } from '@xyflow/react';
import type { Agent, Plan } from './api';

const palette: Record<string,string> = {
  completed:'#22a88b', running:'#e9aa56', failed:'#e06f74',
  skipped:'#7b889d', queued:'#7b889d'
};
export function executionGraph(plan: Plan, agents: Agent[]): {nodes: Node[]; edges: Edge[]} {
  const records = plan.steps || [];
  const valid = new Set(records.map(x => x.id));
  const levels = new Map<string,number>();
  const status = new Map(agents.map(x => [x.agent,x]));
  for (const record of records) {
    let depth = 0;
    for (const predecessor of record.depends_on) depth = Math.max(depth, (levels.get(predecessor) ?? 0) + 1);
    levels.set(record.id, depth);
  }
  const layerIndex = new Map<number,number>();
  const nodes: Node[] = records.map(x => {
    const layer = levels.get(x.id) ?? 0;
    const rank = layerIndex.get(layer) ?? 0;
    layerIndex.set(layer, rank + 1);
    const agent = status.get(x.id);
    const state = agent?.status || 'queued';
    return {
      id: x.id, position: {x: layer * 255, y: rank * 125},
      data: { label: [x.id.replaceAll('_', ' '), state, x.thinking_level || ''].filter(Boolean).join(' · ') },
      draggable: false, selectable: true,
      style: {
        border: '1px solid ' + (palette[state] || '#7b889d'),
        borderLeft: '5px solid ' + (palette[state] || '#7b889d'),
        background: '#182337', color: '#f7f9fd', borderRadius: 12,
        padding: 12, fontSize: 12, minWidth: 205, textTransform: 'capitalize',
        boxShadow: '0 12px 28px rgba(0,0,0,.12)'
      }
    };
  });
  const edges: Edge[] = records.flatMap(x => x.depends_on
    .filter(dependency => valid.has(dependency))
    .map(dependency => ({
      id: dependency + '-' + x.id,
      source: dependency, target: x.id,
      animated: status.get(x.id)?.status === 'running',
      style: {stroke: '#6ca5a6', strokeWidth: 2}
    })));
  return {nodes, edges};
}
