.PHONY: check unit notebook frontend security benchmark
check: notebook unit security frontend
unit:
	python -m unittest discover -s tests -v
notebook:
	python scripts/validate_notebook.py
security:
	python scripts/scan_secrets.py
frontend:
	node --check web/app.js
	python scripts/build_frontend.py --check
	python scripts/validate_frontend.py
benchmark:
	python scripts/benchmark.py benchmarks/data/legacy_failed_turn.jsonl
