#!/usr/bin/env python3
"""Extract the real V9 notebook's self-contained browser UI, including Work Agent.

This executes ONLY the two notebook UI construction cells and a static skill
registry assignment. It never imports Kaggle Secrets or runs cloud models.
"""
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path
import re
import tempfile

ROOT=Path(__file__).resolve().parents[1]
NOTEBOOK=ROOT/'notebooks'/'Rizzler_V9_Kaggle_Gemini_Specialist_Skill_Studio.ipynb'


def build():
    nb=json.loads(NOTEBOOK.read_text(encoding='utf-8'))
    cells=[''.join(c['source']) for c in nb['cells']]
    ui=next(s for s in cells if s.startswith('# ============================================================\n# RIZZLER V5 — Build responsive'))
    work=next(s for s in cells if s.startswith('# 10B — Upgrade professional V5'))
    gallery=next(s for s in cells if s.startswith('# 10B-B — Skill Studio'))
    registry_src=next(s for s in cells if s.startswith('# ============================================================\n# RIZZLER V9 — SPECIALIST ARTIFACT'))
    tree=ast.parse(ui)
    html=ast.literal_eval(tree.body[0].value.args[0])
    registry_assignment=next(n for n in ast.parse(registry_src).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='RIZZLER_SKILL_REGISTRY' for t in n.targets))
    reg_scope={}
    exec(compile(ast.Module(body=[registry_assignment],type_ignores=[]),'<skill-registry>','exec'),reg_scope)
    with tempfile.TemporaryDirectory() as d:
        destination=Path(d)/'index.html'
        destination.write_text(html,encoding='utf-8')
        scope={'RIZZLER_V5_HTML':destination,'RIZZLER_SKILL_REGISTRY':reg_scope['RIZZLER_SKILL_REGISTRY']}
        exec(compile(work,'<notebook-work-ui>','exec'),scope)
        exec(compile(gallery,'<notebook-skills-ui>','exec'),scope)
        html=destination.read_text(encoding='utf-8')
    # The live notebook itself sanitizes these visible legacy phrases.
    html=html.replace('printed in Colab','configured in Kaggle Secrets').replace('Enter the key printed in Colab.','Enter your RIZZLER_ACCESS_KEY from Kaggle Secrets.')
    js='\n'.join(re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>',html,flags=re.S|re.I))
    if not js or '/api/agent/jobs' not in html or '/ws' not in html:
        raise RuntimeError('UI extraction failed; missing voice or Work Agent bridge')
    return html,js

if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--check',action='store_true',help='Fail when committed UI snapshot is stale')
    args=cli.parse_args()
    html,js=build()
    index=ROOT/'web'/'index.html';script=ROOT/'web'/'app.js'
    if args.check:
        assert index.read_text(encoding='utf-8')==html,'Web UI snapshot stale; run scripts/build_frontend.py'
        assert script.read_text(encoding='utf-8')==js,'JS snapshot stale; run scripts/build_frontend.py'
        print('PASS frontend snapshot matches notebook')
    else:
        index.write_text(html,encoding='utf-8')
        script.write_text(js,encoding='utf-8')
        print('Built',len(html),'HTML characters,',len(js),'JS characters')
