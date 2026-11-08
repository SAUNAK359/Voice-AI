#!/usr/bin/env python3
"""Static leak guard; keys are NEVER needed in GitHub Actions."""
from __future__ import annotations
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
PATTERNS={
 'google_api_key':re.compile(r'AIza[0-9A-Za-z_-]{30,}'),
 'openai_api_key':re.compile(r'sk-(?:proj-)?[A-Za-z0-9_-]{24,}'),
 'github_token':re.compile(r'(?:ghp_|gho_|ghs_|github_pat_)[A-Za-z0-9_-]{28,}'),
 'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
}
EXCLUDE={'.git','__pycache__','.pytest_cache','node_modules','.ipynb_checkpoints'}
EXTS={'.py','.ipynb','.json','.yml','.yaml','.html','.js','.css','.md','.txt','.toml','.sh','.env'}

def check(root=ROOT):
    findings=[]; scanned=0
    for path in root.rglob('*'):
        if not path.is_file() or any(p in EXCLUDE for p in path.parts) or path.suffix not in EXTS:
            continue
        if path.name in ('.env','.env.local','.env.production'):
            findings.append((path.relative_to(root).as_posix(),'forbidden_env_file'))
        text=path.read_text(encoding='utf-8',errors='replace')
        scanned+=1
        # A valid notebook must not contain saved outputs or embedded credentials.
        if path.suffix=='.ipynb':
            data=json.loads(text)
            for i,c in enumerate(data['cells']):
                if c.get('outputs'):
                    findings.append((str(path.relative_to(root)),f'code_cell_{i}_outputs'))
        for name,regex in PATTERNS.items():
            if regex.search(text):findings.append((path.relative_to(root).as_posix(),name))
    return scanned,findings

if __name__=='__main__':
    total,issues=check()
    if issues:
        for name,issue in issues:print('FAIL',name,issue)
        raise SystemExit(1)
    print(f'PASS static secret scan: {total} text files; no matching keys or committed .env files')
