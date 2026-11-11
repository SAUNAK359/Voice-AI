#!/usr/bin/env python3
"""Non-destructively announce the app entrypoint and refresh checksums."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'README.md'
old=p.read_text(encoding='utf-8')
note='''# Rizzler — app-first runtime

**Run the modular application:** `python -m rizzler`. Install the lightweight base with `pip install -e '.[test]'` for tests, or `pip install -e '.[voice]'` for actual speech and Gemini. See [app quickstart](APP_QUICKSTART.md), [Phase 0 gates](docs/PHASE_0.md), and the source in `src/rizzler/`. The V9 Kaggle notebook is retained as an optional historical demo; **the new server has not yet migrated all Work Agent features**.

---

'''
if '## App-first quickstart' not in old and not old.startswith(('# Rizzler — app-first runtime', '# Rizzler — application-first voice AI')):
    p.write_text(note+old,encoding='utf-8')
subprocess.run([sys.executable,str(ROOT/'scripts/sync_release_manifest.py')],check=True)
