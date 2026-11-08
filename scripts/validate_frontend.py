#!/usr/bin/env python3
"""Static frontend integration sanity checks; does not promise live microphone tests."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
js=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
assert '<html' in html.lower() and '</html>' in html.lower()
assert all(path in html for path in ('/api/agent/jobs','/api/agent/upload','/api/turn','/ws'))
assert 'v9-skills' in html and 'v6-work' in html
assert not any(x in html for x in ('<configured-in-kaggle-secrets>','OPENAI_API_KEY='))
assert 'function creds()' in js, 'Work Agent auth handler missing'
assert 'content' in html.lower(), 'UI content missing'
assert len(js)>1000
print('PASS frontend voice/agent references and specialist panel')
