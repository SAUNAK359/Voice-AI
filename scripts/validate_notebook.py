#!/usr/bin/env python3
"""Check that the canonical Kaggle notebook is syntactically valid and ordered."""
from __future__ import annotations
import ast
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
NOTEBOOK=ROOT/'notebooks'/'Rizzler_V9_Kaggle_Gemini_Specialist_Skill_Studio.ipynb'


def validate(path: Path=NOTEBOOK) -> dict:
    raw=json.loads(path.read_text(encoding='utf-8'))
    assert raw.get('nbformat') == 4, 'Unsupported notebook format'
    assert raw.get('metadata',{}).get('kernelspec',{}).get('language') == 'python'
    cells=raw.get('cells') or []
    python_count=0
    for i, cell in enumerate(cells):
        assert cell.get('cell_type') in ('code','markdown','raw'),f'Invalid cell type #{i}'
        assert not cell.get('outputs'),f'Saved executable output in cell #{i}'
        if cell.get('cell_type')=='code':
            source=''.join(cell.get('source',[]))
            try: ast.parse(source,filename=f'{path.name}:cell[{i}]')
            except SyntaxError as e: raise SyntaxError(f'Cell #{i}: {e}') from e
            python_count+=1
    src=[''.join(c.get('source',[])) for c in cells]
    def locate(needle):
        matches=[i for i,s in enumerate(src) if needle in s]
        if not matches: raise AssertionError(f'Notebook missing {needle}')
        return matches[0]
    # The historical bug was registering Work Agent routes before the app exists.
    p_app=locate('RIZZLER_V5_APP = FastAPI(')
    p_agent=locate("@RIZZLER_V5_APP.get('/api/agent/schema')")
    p_verify=locate('# 9 — VERIFY VOICE SERVER BOOTSTRAP')
    p_ui=locate('# RIZZLER V5 — Build responsive, self-contained browser UI')
    assert p_app < p_verify < p_agent < p_ui, 'Unsafe server/agent/UI execution order'
    assert all('from fastrtc import' not in s and 'import fastrtc' not in s for s in src), 'FastRTC dependency reintroduced'
    assert any('UserSecretsClient' in s for s in src), 'Kaggle Secrets integration missing'
    assert any('RIZZLER_GEMINI_CLIENT_FACTORY' in s for s in src), 'Gemini factory missing'
    assert any('RIZZLER_LOCAL_WARM and RIZZLER_GEMINI_WARM' in s for s in src), 'Warmup gate missing'
    return {'cells':len(cells),'python_cells':python_count,'server_cell':p_app,'agent_cell':p_agent,'ui_cell':p_ui}

if __name__=='__main__':
    report=validate()
    print('PASS notebook structural audit:',json.dumps(report))
