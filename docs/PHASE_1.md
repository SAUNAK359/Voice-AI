# V10 Phase 1: live-provider qualification and connection isolation

This milestone adds a model-independent provider contract, multiple WebSocket
connections with per-session ownership, and a reproducible real-model qualification
command. ASR/Gemini/TTS still share one inference lock. It does **not** enable
multiple concurrent GPU turns.

## Kaggle T4 execution

Clone the latest repository into Kaggle; install with GPU enabled:

```bash
pip install -e '.[voice,cuda12]'
export RIZZLER_ASR_DEVICE=cuda
export RIZZLER_ACCESS_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Set GEMINI_API_KEY from a Kaggle Secret in a notebook cell, **not in Git or a
committed shell command**:

```python
import os
from kaggle_secrets import UserSecretsClient
os.environ["GEMINI_API_KEY"] = UserSecretsClient().get_secret("GEMINI_API_KEY")
os.environ["RIZZLER_ASR_DEVICE"] = "cuda"
```

On some Linux T4 images, set `LD_LIBRARY_PATH` to include the installed
nvidia/cublas/lib and nvidia/cudnn/lib directories **before starting Python**
(see APP_QUICKSTART.md). Supply your own 1–10 second mono PCM16 WAV
(recorded speech, not empty audio), then run:

```bash
python scripts/qualify_live.py --wav sample.wav --report qualification.json --require-cuda --repeat 3
```

The run fails if dependencies, CUDA visibility, Gemini credentials, any model
stage, or produced PCM are missing. The report records no raw transcript or
audio. It measures *server submission to first PCM*, not actual browser-audible
latency. Cold starts and downloads count and may increase latency.

## What is and is not accepted

- CPU tests verify session ownership, same-session takeover rejection,
  WAV input validation, and the end-to-end event contract with fakes.
- GitHub Actions can validate Python 3.11–3.13 and the browser syntax.
- Real T4/CUDA, live Gemini, KittenTTS intelligibility, and mobile browser
  first-audible latency **require external evidence**. Do not mark them
  complete until the report is produced in the target environment.
- The V9 Work Agent notebook is preserved. Its 17 specialists are not yet
  migrated into the V10 backend; this patch does not fabricate equivalent
  functionality.
- The shared access key remains a demo-only security boundary. Session IDs
  are not verified user identities. Never expose this app as a multi-tenant
  public service before the Phase 5 authentication upgrade.
