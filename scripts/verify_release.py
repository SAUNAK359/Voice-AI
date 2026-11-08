#!/usr/bin/env python3
"""Verify manifest-listed repository files have not changed since packaging."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
manifest=ROOT/'RELEASE_MANIFEST.json'
if not manifest.exists():
    raise SystemExit('Missing release manifest')
ledger=json.loads(manifest.read_text())
assert ledger['schema_version']==1
for row in ledger['files']:
    target=(ROOT/row['path']).resolve()
    if ROOT not in target.parents or not target.is_file():
        raise ValueError(f'Missing or unsafe path: {row["path"]}')
    data=target.read_bytes()
    if hashlib.sha256(data).hexdigest()!=row['sha256'] or len(data)!=row['bytes']:
        raise ValueError(f'Changed artifact: {row["path"]}')
print(f'PASS release manifest: {len(ledger["files"])} files')
