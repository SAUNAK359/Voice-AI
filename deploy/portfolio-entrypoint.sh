#!/usr/bin/env bash
# The GPU container's independent wall-clock safety deadline.
set -euo pipefail
: "${RIZZLER_STACK_DEADLINE:?Demo deadline is required}"
: "${RIZZLER_ACCESS_KEY:?Voice key is required}"
: "${RIZZLER_WORK_SIGNING_KEY:?Work signing key is required}"
: "${GEMINI_API_KEY:?Model key is required}"
[[ "${RIZZLER_STACK_DEADLINE}" =~ ^[0-9]{10}$ ]] || exit 2
remaining=$(( RIZZLER_STACK_DEADLINE - $(date +%s) ))
if (( remaining <= 0 || remaining > 1800 )); then
  echo "Portfolio lease expired or invalid; refusing to start."
  exit 0
fi
python -m rizzler.work_worker --root /tmp/rizzler-work &
worker=$!
python -m rizzler &
web=$!
# After the absolute deadline, terminate both processes even if the gateway
# host has lost power. Provider termination runs separately from the gateway.
(sleep "${remaining}"; kill -TERM "$worker" "$web" 2>/dev/null || true) &
watchdog=$!
trap 'kill -TERM "$web" "$worker" "$watchdog" 2>/dev/null || true' TERM INT EXIT
wait -n "$worker" "$web" "$watchdog" || true
exit 0
