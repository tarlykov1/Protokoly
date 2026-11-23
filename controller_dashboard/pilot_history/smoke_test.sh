#!/usr/bin/env bash
# Safe route-checks without printing or requiring any API credentials.
set -euo pipefail
URL="${PILOT_BASE_URL:-http://127.0.0.1:8000}"
check() {
  local path="$1" expected="$2" code
  code="$(curl --max-time 8 --silent --output /dev/null --write-out '%{http_code}' "$URL$path")" || code='000'
  printf '%-56s HTTP %s (expected %s)\n' "$path" "$code" "$expected"
  [[ "$code" == "$expected" ]]
}
check /controller-pilot-test/overview/ 200
check /controller-pilot-test/overview/overview_v67.js 200
check /controller-pilot-test/timeline/ 200
# No token supplied: authorization MUST be enforced.
check /controller-pilot-test/overview/data 401
echo 'All four checks passed; open overview in the browser and authenticate with the pilot token.'
