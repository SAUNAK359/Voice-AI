## Summary
Describe what changed, especially notebook cell order or API behavior.

## Verification
- [ ] `python scripts/validate_notebook.py`
- [ ] `python -m unittest discover -s tests -v`
- [ ] `python scripts/scan_secrets.py`
- [ ] `node --check web/app.js`
- [ ] Live Kaggle GPU tests (if model/runtime was modified; attach redacted results)

## Security
- [ ] No secrets, private transcripts, notebooks outputs, generated user data, or external account tokens committed
- [ ] Public demo modes keep authentication enabled

## Benchmark disclosure
Provide environment, model IDs, warmup count, N, latency definitions, TTFT p50/p95 and limitations.
