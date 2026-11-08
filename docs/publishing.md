# Publishing to SAUNAK359/Voice-AI

## Required GitHub access

The connected GitHub account can access `SAUNAK359` but GitHub currently returned HTTP 404 for `SAUNAK359/Voice-AI`; the repository was not present among the GitHub App's selected repositories. Before a remote push:

1. Open https://github.com/SAUNAK359/Voice-AI and verify the repository exists. If it does not, create it on GitHub without a starter README or license (the showcase package has its own README and licensing decision is intentionally deferred).
2. Open the GitHub App installation settings and grant repository access to **Voice-AI**. Choose the existing installed app from your GitHub settings; do not share GitHub tokens in chat.
3. Make sure the repository has Actions enabled. The first CI run will perform CPU tests and static checks, not Kaggle GPU inference.

## Local push to a newly created, empty repository

```bash
unzip Voice-AI_Showcase_Repository.zip -d /tmp/rizzler-checkout
cd /tmp/rizzler-checkout/voice-ai-showcase
make check
git init -b main
git add .
git commit -m "feat: release Rizzler V9 Kaggle voice and Gemini work-agent showcase"
git remote add origin https://github.com/SAUNAK359/Voice-AI.git
git push -u origin main
```

Use your GitHub-authenticated Git credential manager or SSH key; do not embed personal access tokens in commands. **If the repository already contains files, clone it first, create a feature branch, copy the showcase files into that checkout, and open a pull request instead of overwriting existing history.**

## After publishing

Check `.github/workflows/ci.yml` and optional public-repository CodeQL. Do not claim Actions passed until GitHub actually reports successful runs. Inspect the published repository for missing UI assets, broken Markdown links, scanned credentials and notebook outputs. Add a real Kaggle smoke-test badge only after a measured GPU run is available.
