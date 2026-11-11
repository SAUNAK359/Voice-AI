# Rizzler — app-first quickstart

This is the new standard application. The V9 notebook stays available for historical Work Agent features until their controlled migration is completed.

## Install on local CPU

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -e '.[voice,test]'
```

Set secrets using your OS environment (do not paste into source code):

```bash
export RIZZLER_ACCESS_KEY='choose-at-least-16-private-random-chars'
export GEMINI_API_KEY='your-key-from-secret-manager'
export RIZZLER_ASR_DEVICE=cpu
python -m rizzler
```

On Windows PowerShell, set credentials using `$env:RIZZLER_ACCESS_KEY='...'` and `$env:GEMINI_API_KEY='...'` rather than Bash `export`.

Open <http://localhost:8000/> in a browser (localhost permits microphone access). For phone access, use your own trusted HTTPS/WSS endpoint. This server uses one inference turn at a time during Phase 0.

## On an NVIDIA T4

```bash
pip install -e '.[voice,cuda12]'
export RIZZLER_ASR_DEVICE=cuda
# Linux: CUDA12 libraries may need discovery in a NEW Python process:
export LD_LIBRARY_PATH="$(python - <<'PY'
import site
from pathlib import Path
print(':'.join(str(p) for b in site.getsitepackages() for n in ('cublas','cudnn') if (p:=Path(b)/'nvidia'/n/'lib').is_dir()))
PY
):${LD_LIBRARY_PATH:-}"
python -m rizzler
```

Install the NVIDIA driver on the host; package wheels do not include the GPU driver. GPU measurements from prior notebooks are **not** automatically transferrable to this modular runtime.

## Test without secrets, downloads or external models

```bash
pip install -e '.[test]'
pytest -q tests/test_app_phase0.py
node --check src/rizzler/web/app.js
```

Run `python -m rizzler` only after configuring `RIZZLER_ACCESS_KEY`. An invalid/missing key intentionally prevents server startup.

## Repository migration

This package is designed to **overlay the existing `Voice-AI` repo**, not replace its benchmark evidence or notebooks. Copy the overlay files into a fresh clone, regenerate the old source-package checksum manifest with `python scripts/sync_release_manifest.py`, run both original CI and new app tests, review the git diff, and push through your own authenticated GitHub session.

See `docs/PHASE_0.md` for what Phase 0 does and does not yet deliver.
