#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common-demo.sh"
require_env
compose build
compose up -d db
until compose exec -T db pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do sleep 2; done
compose run --rm app alembic upgrade head
compose up -d app nginx
BASE_URL=${PUBLIC_BASE_URL:-http://localhost}
BASE_URL=${BASE_URL%/} scripts/smoke-test.sh
[[ "${SEED_DEMO:-false}" == "true" ]] && scripts/seed-demo.sh
echo "Demo is available at ${PUBLIC_BASE_URL:-http://localhost}"
