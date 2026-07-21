#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common-demo.sh"
require_env
BACKUP=${1:-}
[[ -n "$BACKUP" && -d "$BACKUP" ]] || { echo "Usage: scripts/restore.sh backups/<timestamp>" >&2; exit 1; }
read -r -p "Restore $BACKUP and overwrite current database/uploads? Type RESTORE: " CONFIRM
[[ "$CONFIRM" == "RESTORE" ]] || { echo "Cancelled"; exit 1; }
compose stop app nginx || true
compose up -d db
until compose exec -T db pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do sleep 2; done
compose exec -T db dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB"
compose exec -T db createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < "$BACKUP/db.dump"
cat "$BACKUP/uploads.tar.gz" | compose run --rm --no-deps app sh -c 'cd /app && tar -xzf -'
compose run --rm app alembic upgrade head
compose up -d app nginx
BASE_URL=${PUBLIC_BASE_URL:-http://localhost} scripts/smoke-test.sh
