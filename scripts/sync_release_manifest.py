#!/usr/bin/env python3
"""Refresh legacy integrity inventory after changes; ignores generated runtime files."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
manifest = ROOT / 'RELEASE_MANIFEST.json'
ignore = {'.git', '.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
          'logs', 'build', 'dist', 'rizzler_voice_intelligence.egg-info'}
rows = []
for path in sorted(ROOT.rglob('*')):
    if not path.is_file() or path == manifest or any(part in ignore for part in path.relative_to(ROOT).parts):
        continue
    if path.suffix in ('.pyc', '.pyo'):
        continue
    if path.name in ('.env', 'install.log'):
        continue
    relative = path.relative_to(ROOT).as_posix()
    # Historical benchmark evidence belongs in the existing repo, not source ZIP.
    raw = path.read_bytes()
    rows.append({'path': relative, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
manifest.write_text(json.dumps({'schema_version': 1,
    'description': 'Source checkout integrity inventory (not a cryptographic signature)',
    'files': rows}, indent=2) + '\n', encoding='utf-8')
print(f'Updated {len(rows)} entries: {manifest}')
