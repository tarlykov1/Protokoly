#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common-demo.sh"
require_env
[[ "${DEMO_MODE}" == "true" ]] || { echo "DEMO_MODE must be true" >&2; exit 1; }
compose run --rm app python -m app.cli.seed_demo
compose run --rm app python -m app.cli.generate_demo_docx >/dev/null
echo "Guided demo: ${PUBLIC_BASE_URL:-http://localhost}/demo/guided"
