#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${CONTROLLER_PILOT_APP_DIR:-/webapp/app/controller_dashboard_test}"
if [[ ! -d "$DEST" || ! -f "$DEST/timeline_v6.py" || ! -f "$DEST/overview_v67.html" ]]; then
  echo "На сервере нужна уже установленная v6.7 (timeline_v6.py + overview_v67.html)" >&2
  exit 2
fi
if grep -q 'V71_GROUP734_ROUTES_BEGIN' "$DEST/timeline_v6.py"; then
  echo "v7.1 уже установлена; повторную запись не выполняем." >&2
  exit 2
fi
if [[ ! -d "$DEST/data" || -L "$DEST/data" ]]; then
  echo "Каталог data должен существовать и не быть символьной ссылкой" >&2
  exit 2
fi
python3 - "$HERE" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1]); files=[
    'group734_v71.py', 'collect_group734_v71.py', 'roster_probe_v70.py',
    'group734_routes_v71.py', 'dashboard_group734_v71.html',
    'dashboard_group734_v71.js', 'dashboard_group734_v71.css',
]
for file in files:
    p=root/file
    if not p.is_file():
        raise SystemExit('Missing file: '+str(p))
    if p.suffix=='.py':
        compile(p.read_bytes(), str(p), 'exec')
print('Python syntax: OK')
PY
STAMP="$(date +%Y%m%d_%H%M%S)"
cp -p "$DEST/timeline_v6.py" "$DEST/timeline_v6.py.bak.v7_1_$STAMP"
for file in group734_v71.py collect_group734_v71.py roster_probe_v70.py group734_routes_v71.py dashboard_group734_v71.html dashboard_group734_v71.js dashboard_group734_v71.css; do
  if [[ -e "$DEST/$file" || -L "$DEST/$file" ]]; then
    echo "Новый файл уже существует: $DEST/$file; ручная сверка перед перезаписью обязательна." >&2
    exit 2
  fi
done
for file in group734_v71.py collect_group734_v71.py roster_probe_v70.py group734_routes_v71.py dashboard_group734_v71.html dashboard_group734_v71.js dashboard_group734_v71.css; do
  install -m 0644 "$HERE/$file" "$DEST/$file"
done
python3 - "$DEST/timeline_v6.py" <<'PY'
from pathlib import Path
import os
import sys
import tempfile
p=Path(sys.argv[1]); original=p.read_text(encoding='utf-8')
if 'V71_GROUP734_ROUTES_BEGIN' in original:
    raise SystemExit('The routes already exist')
if 'router = APIRouter(' not in original or '@router.get("/overview/data")' not in original:
    raise SystemExit('Unexpected pilot history module; stopped before modification')
addition='''

# V71_GROUP734_ROUTES_BEGIN – isolated aggregate view, no production route changes
if __package__:
    from .group734_routes_v71 import register_routes as _register_group734_routes
else:
    from group734_routes_v71 import register_routes as _register_group734_routes
_register_group734_routes(router, _authorize, ROOT)
# V71_GROUP734_ROUTES_END
'''
content=original+addition
compile(content,str(p),'exec')
fd,path=tempfile.mkstemp(prefix='.timeline_v71_',dir=str(p.parent))
try:
    with os.fdopen(fd,'w',encoding='utf-8') as out:
        out.write(content)
        out.flush()
        os.fsync(out.fileno())
    os.chmod(path,p.stat().st_mode & 0o777)
    os.replace(path,p)
finally:
    if os.path.exists(path):
        os.unlink(path)
print('Registered test group734 routes')
PY
printf '%s\n' "$STAMP" > "$HERE/.last_install_stamp"
echo "Installed v7.1 test-only module. Backup: $DEST/timeline_v6.py.bak.v7_1_$STAMP"
echo "No change to main.py, pilot.sqlite, pilot_comment_snapshots.sqlite or production controller."
echo "Activation requires a coordinated restart of bitrix-dashboards."
