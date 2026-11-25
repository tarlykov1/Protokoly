#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET=/tmp/controller_timeline_v6_8_probe/live_probe_v68.py
if [[ ! -f "$TARGET" ]]; then
  echo "Не найден установленный модуль: $TARGET" >&2
  exit 2
fi
python3 - "$HERE/../../live_probe_v68.py" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
compile(p.read_bytes(), str(p), 'exec')
print('Python syntax: OK')
PY
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP="${TARGET}.bak.shape_${STAMP}"
cp -p "$TARGET" "$BACKUP"
cp "$HERE/../../live_probe_v68.py" "$TARGET"
python3 - "$TARGET" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); compile(p.read_bytes(), str(p), 'exec')
print('Installed safely:', p)
PY
echo "Backup: $BACKUP"
echo "No changes to /webapp, SQLite, main.py or systemd. No restart needed."
