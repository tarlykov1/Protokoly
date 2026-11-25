#!/usr/bin/env bash
# v6.7: only test timeline and a new read-only overview. Never writes to SQLite.
set -euo pipefail
APP="${APP_DIR:-/webapp/app}"
DEST="$APP/controller_dashboard_test"
SOURCE="$(cd "$(dirname "$0")" && pwd)"
FILES=(timeline_v6.py timeline_v6.js timeline_v6.css timeline_v6.html overview_v67.py overview_v67.html overview_v67.js overview_v67.css)
[[ -f "$DEST/timeline_v6.py" && -f "$DEST/comment_archive_v66.py" && -d "$DEST/data" ]] || {
  echo 'ERROR: install v6.6 and confirm test controller module first' >&2; exit 1;
}
[[ -w "$DEST" ]] || { echo 'ERROR: no permission to update test module' >&2; exit 1; }
for f in "${FILES[@]}"; do [[ -f "$SOURCE/$f" ]] || { echo "Missing file: $f" >&2; exit 1; }; done
python3 - "$SOURCE" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
for f in ('timeline_v6.py','overview_v67.py'):
    compile((p/f).read_bytes(),str(p/f),'exec')
print('Python syntax: OK; __pycache__ unchanged')
PY
if command -v node >/dev/null 2>&1; then
  node --check "$SOURCE/timeline_v6.js"
  node --check "$SOURCE/overview_v67.js"
  echo 'JavaScript syntax: OK'
fi
STAMP="$(date +%Y%m%d_%H%M%S)"
TO_RESTORE=()
TEMPS=()
rollback_failed() {
  echo 'Install failed: restoring prior test files' >&2
  for name in "${TO_RESTORE[@]}"; do
    if [[ -f "$DEST/$name.bak.v6_7.$STAMP" ]]; then cp -p "$DEST/$name.bak.v6_7.$STAMP" "$DEST/$name";
    else rm -f "$DEST/$name"; fi
  done
}
cleanup() { for t in "${TEMPS[@]}"; do rm -f "$t"; done; }
trap cleanup EXIT
trap rollback_failed ERR
for name in "${FILES[@]}"; do
  if [[ -e "$DEST/$name" ]]; then cp -p "$DEST/$name" "$DEST/$name.bak.v6_7.$STAMP"; fi
  temp="$DEST/$name.tmp.v6_7.$$"
  TEMPS+=("$temp")
  install -m 644 "$SOURCE/$name" "$temp"
  mv -f "$temp" "$DEST/$name"
  TO_RESTORE+=("$name")
done
trap - ERR
printf '\nInstalled v6.7 into %s\nBackups stamp: %s\n' "$DEST" "$STAMP"
for name in "${FILES[@]}"; do
  if [[ -f "$DEST/$name.bak.v6_7.$STAMP" ]]; then echo "Backup: $DEST/$name.bak.v6_7.$STAMP"; fi
done
printf '%s\n' 'UNCHANGED: pilot.sqlite, pilot_comment_snapshots.sqlite, main.py, production controller, systemd config.'
printf '%s\n' 'Activation: coordinated systemctl restart bitrix-dashboards; then Ctrl+F5.'
