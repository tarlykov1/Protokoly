#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$(cd "$HERE/../.." && pwd)"
DEST="${CONTROLLER_V68_TARGET:-/tmp/controller_timeline_v6_8_probe}"
if [[ ! -d "$DEST" || ! -f "$DEST/probe_cli_v68.py" || ! -f "$DEST/live_probe_v68.py" ]]; then
  echo "Existing diagnostic installation not found: $DEST" >&2
  exit 2
fi
python3 - "$SOURCE/probe_cli_v68.py" "$SOURCE/live_probe_v68.py" <<'PY'
from pathlib import Path
import sys
for filename in sys.argv[1:]:
    p=Path(filename)
    compile(p.read_bytes(), str(p), 'exec')
print('Python syntax: OK')
PY
STAMP="$(date +%Y%m%d_%H%M%S)"
for filename in probe_cli_v68.py live_probe_v68.py; do
  cp -p "$DEST/$filename" "$DEST/$filename.bak.rawshape_$STAMP"
  temp="$(mktemp "$DEST/.${filename}.tmp.XXXXXXXX")"
  cp "$SOURCE/$filename" "$temp"
  chmod --reference="$DEST/$filename" "$temp"
  mv -f "$temp" "$DEST/$filename"
  echo "Updated: $DEST/$filename (backup .bak.rawshape_$STAMP)"
done
echo "No systemd restart, production application or SQLite changes."
