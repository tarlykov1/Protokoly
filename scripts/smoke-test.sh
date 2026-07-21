#!/usr/bin/env bash
set -euo pipefail
BASE_URL=${BASE_URL:-http://localhost}
BASE_URL=${BASE_URL%/}
AUTH=()
if [[ -n "${BASIC_AUTH_USER:-}" || -n "${BASIC_AUTH_PASSWORD:-}" ]]; then
  AUTH=(-u "${BASIC_AUTH_USER}:${BASIC_AUTH_PASSWORD}")
fi
for path in /health /ready / /demo /demo/dashboard /protocols /protocols/import /publication-runs; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' "${AUTH[@]}" "$BASE_URL$path")
  [[ "$code" =~ ^(200|303)$ ]] || { echo "Smoke failed for $path: HTTP $code" >&2; exit 1; }
  echo "OK $path ($code)"
done
