# Contributing

The canonical GPU demo is `notebooks/Rizzler_V9_Kaggle_Gemini_Specialist_Skill_Studio.ipynb`. Python modules in `src/rizzler/` define reusable contracts and quality gates but do not independently launch a GPU voice service.

Before opening a PR, run:

```bash
python scripts/validate_notebook.py
python -m unittest discover -s tests -v
python scripts/scan_secrets.py
node --check web/app.js
python scripts/validate_frontend.py
```

For changes involving Gemini, Whisper, KittenTTS, Kaggle Secrets, or real-time browser audio, attach **redacted real Kaggle results**. A green CPU CI build is necessary but insufficient to claim live voice performance. Never commit notebook outputs, user speech/transcripts, environment files, or API keys.

PRs must preserve the voice-server initialization before Work Agent API registration and preserve cancellation generation IDs. For artifact changes, include a representative data-backed file and structural plus visual validation.
