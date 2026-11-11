# Rizzler V10 — Phase 3: Gemini reliability and reasoning

## Delivered in the standalone application

- Dependency-free deterministic routing to **fast**, **deep**, **guarded**, or **local exact arithmetic**.
- Structural separation of past user/model turns from the immutable Gemini system instruction.
- Process-local request-per-minute and estimated-token-per-minute admission, bounded quota waiting and attempts.
- 401/403 fail closed; 429 stops without switching models on the same account; 404 permits **explicitly configured** fallback; retryable 5xx failures use bounded jittered backoff **only before visible text**.
- Per-model, process-local circuit breakers; cancelled/partial turns never become successful telemetry.
- Optional thinking-level request field, **off by default** for compatibility with models that do not accept it.
- Usage metadata and estimated cost only when token counts and price configuration are known.
- Authenticated `GET /api/provider/metrics` returns window aggregates, not raw prompts, tokens, audio or credentials.
- Reproducible input-validated GSM8K and category-balanced MMLU-Pro JSONL evaluators, with dataset SHA256, seed, sample count, per-case outcomes, failures and accuracy denominator.

## Configuration

Set these as environment variables (see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `RIZZLER_GEMINI_MODEL` | `gemini-3.5-flash-lite` | Requested primary model ID; provider availability still requires live confirmation |
| `RIZZLER_GEMINI_FALLBACK_MODELS` | empty | Comma-separated explicit alternatives (max 3) |
| `RIZZLER_GEMINI_RPM` | 12 | Local RPM admission budget |
| `RIZZLER_GEMINI_TPM` | 24000 | Conservative estimated input+output TPM budget |
| `RIZZLER_GEMINI_MAX_ATTEMPTS` | 3 | Maximum attempts including fallback |
| `RIZZLER_GEMINI_QUOTA_WAIT` | 1.5 | Maximum admission wait in seconds |
| `RIZZLER_GEMINI_ENABLE_THINKING` | false | Enables model-native thinking levels when supported |
| `RIZZLER_GEMINI_INPUT_USD_PER_MILLION` | unset | Optional price reference; omitted costs are unknown |
| `RIZZLER_GEMINI_OUTPUT_USD_PER_MILLION` | unset | Optional price reference; omitted costs are unknown |

All quota controls are per-process, not distributed account-wide enforcement.
Actual provider quota and model/API availability may differ. For distributed
production use, move quota counters and circuit state to shared storage and
configure real user authentication (Phase 5).

## Real evaluation, not fabricated score

Acquire/version your own licensed GSM8K and MMLU-Pro JSONL files. Schema:
- GSM8K: `{"id":"g1","question":"...","answer":"... #### 42"}`
- MMLU-Pro: `{"id":"m1","question":"...","options":["...","..."],"answer":"B","category":"physics"}`
- Factual smoke: `{"id":"f1","question":"...","answer":"canonical exact answer","aliases":["accepted alias"]}`

```bash
python scripts/evaluate_reasoning.py --suite gsm8k --dataset /path/gsm8k.jsonl --validate
python scripts/evaluate_reasoning.py --suite mmlu_pro --dataset /path/mmlu_pro.jsonl --validate

# Requires valid GEMINI_API_KEY and RIZZLER_ACCESS_KEY, performs real API calls:
python scripts/evaluate_reasoning.py --suite gsm8k --dataset /path/gsm8k.jsonl --seed 42 --limit 0 --output gsm8k-live.json
python scripts/evaluate_reasoning.py --suite mmlu_pro --dataset /path/mmlu_pro.jsonl --seed 42 --limit 1000 --output mmlu-pro-live.json
```

The MMLU-Pro sampler interleaves categories for a balanced limited subset.
`--limit 0` means the **entire supplied file**, not an authoritative full
benchmark unless the input actually contains the entire dataset. Failure,
timeout or empty answer counts as incorrect. Final numeric/choice extraction
is strict and may undercount semantically correct but differently formatted answers.

## Evidence and release gates

| Gate | Current evidence |
|---|---|
| Offline routing, quotas, retries, fallback, telemetry, scorer | CI regression suite |
| Native Gemini SDK on configured models | Requires authenticated live qualification |
| Provider success ≥99% within quotas | Requires representative live traffic |
| GSM8K full and MMLU-Pro representative accuracy | Requires external dataset and live output JSON |
| Hallucination/factuality improvement | Not established by exact-match evaluation alone |
| Provider cost | Unknown unless real token metadata and prices are supplied |
| Reasoning latency improvement | Requires controlled baseline vs optimized comparison |

The local arithmetic evaluator is an exact arithmetic check for a narrow syntax,
**not** a general mathematical proof checker. Broad answer verification remains
a separate release gate. Do not label Phase 3 production-qualified on CI alone.
