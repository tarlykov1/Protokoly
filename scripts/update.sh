#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common-demo.sh"
require_env
scripts/backup.sh
compose build
compose run --rm app alembic upgrade head
compose up -d app nginx
if ! BASE_URL=${PUBLIC_BASE_URL:-http://localhost} scripts/smoke-test.sh; then
  echo "Update smoke test failed. Roll back code, then run: scripts/restore.sh <backup-dir>" >&2
  exit 1
fi
