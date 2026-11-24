#!/usr/bin/env bash
set -euo pipefail
DEST="${CONTROLLER_PILOT_APP_DIR:-/webapp/app/controller_dashboard_test}"
STAMP="${1:-}"
if [[ ! "$STAMP" =~ ^[0-9]{8}_[0-9]{6}$ ]]; then
  echo 'Usage: bash rollback.sh YYYYMMDD_HHMMSS' >&2
  exit 2
fi
BACKUP="$DEST/timeline_v6.py.bak.v7_1_$STAMP"
if [[ ! -f "$BACKUP" ]]; then
  echo "Backup not found: $BACKUP" >&2
  exit 2
fi
cp -p "$BACKUP" "$DEST/timeline_v6.py"
for file in group734_v71.py collect_group734_v71.py roster_probe_v70.py group734_routes_v71.py dashboard_group734_v71.html dashboard_group734_v71.js dashboard_group734_v71.css; do
  rm -f -- "$DEST/$file"
done
echo 'Application modules restored; aggregate data not deleted.'
echo 'A coordinated service restart is required to activate the previous routes.'
