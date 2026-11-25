#!/usr/bin/env bash
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="/tmp/roster_probe_v70.py"
python3 - "$SRC/roster_probe_v70.py" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
compile(p.read_bytes(),str(p),'exec')
print('Python syntax: OK')
PY
if [ -f "$TARGET" ]; then
  cp -p "$TARGET" "$TARGET.bak.$(date +%Y%m%d_%H%M%S)"
fi
install -m 0644 "$SRC/roster_probe_v70.py" "$TARGET"
echo "Installed: $TARGET"
echo 'No systemd restart, SQLite or production files changed.'
