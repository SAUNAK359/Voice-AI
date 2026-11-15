#!/usr/bin/env python3
"""Validate the committed release inventory against every tracked source file.

Uses Git-compatible blob checksums; this inventory detects accidental drift,
but is not a signed release attestation.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
manifest=ROOT/"RELEASE_MANIFEST.json"
if not manifest.is_file():raise SystemExit("Missing release manifest")
ledger=json.loads(manifest.read_text(encoding="utf-8"))
if ledger.get("schema_version")!=2:raise ValueError("Release manifest v2 required")
rows=ledger.get("files")
if not isinstance(rows,list) or not rows:raise ValueError("Empty release manifest")
paths=set()
for row in rows:
    rel=row["path"]
    if not isinstance(rel,str) or rel in paths or rel=="RELEASE_MANIFEST.json":
        raise ValueError("Duplicate or forbidden inventory entry")
    paths.add(rel)
    path=(ROOT/rel).resolve()
    if ROOT not in path.parents or not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing or unsafe path: {rel}")
    data=path.read_bytes()
    digest=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
    if digest!=row["git_blob_sha1"] or len(data)!=row["bytes"]:
        raise ValueError(f"Changed artifact: {rel}")
if (ROOT/".git").exists():
    committed=subprocess.check_output(["git","ls-files","-z"],cwd=ROOT)
    expected={p.decode() for p in committed.split(b"\0") if p and p!=b"RELEASE_MANIFEST.json"}
    if paths!=expected:
        raise ValueError("Release inventory incomplete: "+str(sorted(expected-paths)[:10]))
print(f"PASS release inventory: {len(rows)} tracked files")
