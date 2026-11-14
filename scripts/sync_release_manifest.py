#!/usr/bin/env python3
"""Regenerate the complete tracked-source inventory after reviewing changes."""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
raw=subprocess.check_output(["git","ls-files","-z"],cwd=ROOT)
paths=sorted(p.decode() for p in raw.split(b"\0") if p and p!=b"RELEASE_MANIFEST.json")
rows=[]
for rel in paths:
    path=ROOT/rel
    if not path.is_file() or path.is_symlink():raise ValueError("Unsafe tracked source: "+rel)
    data=path.read_bytes()
    rows.append({"path":rel,"bytes":len(data),
                 "git_blob_sha1":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()})
out={"schema_version":2,"description":"Tracked-source Git blob integrity inventory; not a signed artifact","files":rows}
(ROOT/"RELEASE_MANIFEST.json").write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
print(f"Updated release inventory: {len(rows)} files")
