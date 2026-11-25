#!/usr/bin/env bash
# Code-only rollback, does not remove any database or captured comments.
set -euo pipefail
STAMP="${1:-}"
[[ "$STAMP" =~ ^[0-9]{8}_[0-9]{6}$ ]] || { echo 'Usage: bash rollback.sh YYYYMMDD_HHMMSS' >&2; exit 1; }
DEST="${APP_DIR:-/webapp/app}/controller_dashboard_test"
FILES=(timeline_v6.py timeline_v6.js timeline_v6.css timeline_v6.html overview_v67.py overview_v67.html overview_v67.js overview_v67.css)
for f in timeline_v6.py timeline_v6.js timeline_v6.css timeline_v6.html; do
  [[ -f "$DEST/$f.bak.v6_7.$STAMP" ]] || { echo "Missing required backup for $f" >&2; exit 1; }
done
for f in "${FILES[@]}"; do
  if [[ -f "$DEST/$f.bak.v6_7.$STAMP" ]]; then cp -p "$DEST/$f.bak.v6_7.$STAMP" "$DEST/$f";
  else rm -f "$DEST/$f"; fi
done
echo 'v6.7 test code reverted. All SQLite data preserved. Coordinated service restart needed.'
