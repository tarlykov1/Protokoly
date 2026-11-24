#!/usr/bin/env bash
set -euo pipefail
BASE="${CONTROLLER_PILOT_URL:-http://127.0.0.1:8000}"
check(){
 local route="$1" expected="$2" actual
 actual="$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "$BASE$route")"
 echo "$route : $actual (expected $expected)"
 [[ "$actual" == "$expected" ]]
}
check /controller-pilot-test/overview/ 200
check /controller-pilot-test/overview/group734/ 200
check /controller-pilot-test/overview/group734/app.js 200
check /controller-pilot-test/overview/group734/styles.css 200
check /controller-pilot-test/overview/group734/data 401
