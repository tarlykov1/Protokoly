#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common-demo.sh"
require_env
TS=$(date -u +%Y%m%dT%H%M%SZ)
DEST="backups/$TS"
mkdir -p "$DEST"
compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom > "$DEST/db.dump"
compose run --rm --no-deps app sh -c 'cd /app && tar -czf - uploads data/generated-docx 2>/dev/null || true' > "$DEST/uploads.tar.gz"
cat > "$DEST/manifest.txt" <<MANIFEST
date=$TS
app_version=${APP_VERSION:-unknown}
git_commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
compose_file=$COMPOSE_FILE
MANIFEST
find backups -mindepth 1 -maxdepth 1 -type d -mtime +"${BACKUP_RETENTION_DAYS:-14}" -print -exec rm -rf {} +
echo "Backup created: $DEST"
