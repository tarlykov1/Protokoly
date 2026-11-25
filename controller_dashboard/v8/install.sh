#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
sha256sum -c --quiet SHA256SUMS
mode=${1:-}
case "$mode" in
backend)
  dest=/opt/controller-v8
  unit=/etc/systemd/system/controller-v8.service
  [[ ! -e "$dest" && ! -L "$dest" && ! -e "$unit" && ! -L "$unit" ]] || { echo "v8 уже установлена"; exit 2; }
  py=${V8_PYTHON:-$(command -v python3)}
  [[ "$py" =~ ^/[a-zA-Z0-9_./-]+$ && -x "$py" ]]
  [[ -d /webapp/app/protocol_dashboard && -f /webapp/app/data/memo_activity_cache.json ]]
  PYTHONPATH=/webapp/app "$py" -c 'import fastapi, uvicorn; from protocol_dashboard import store,service'
  install -d -m 0750 /etc/controller-v8
  if [[ ! -e /etc/controller-v8/server.env ]]; then
    (umask 077; set -o noclobber; "$py" -c 'import secrets;print("V8_TOKEN="+secrets.token_hex(32))' > /etc/controller-v8/server.env)
  fi
  mkdir "$dest"
  trap 'systemctl disable --now controller-v8.service >/dev/null 2>&1 || true; rm -rf -- "$dest"; rm -f -- "$unit"; systemctl daemon-reload' ERR
  cp -R server "$dest/server"
  echo "controller-dashboard-v8.0" > "$dest/.controller-v8"
  printf '#!/bin/sh\nexec %s -m uvicorn service:app --app-dir /opt/controller-v8/server --host 127.0.0.1 --port 18108\n' "$py" > "$dest/start"
  chmod 755 "$dest/start"
  install -m 0644 controller-v8.service "$unit"
  systemctl daemon-reload
  systemctl start controller-v8.service
  ok=0
  for n in {1..20}; do
    status=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:18108/observe || true)
    if [[ "$status" == 403 ]] && systemctl is-active --quiet controller-v8.service; then ok=1; break; fi
    sleep 1
  done
  if [[ "$ok" != 1 ]]; then systemctl stop controller-v8.service; false; fi
  systemctl enable controller-v8.service
  ;;
portal)
  root=$(realpath -e "${2:?Укажите DOCUMENT_ROOT Битрикс24}")
  [[ -f "$root/bitrix/modules/main/include/prolog_before.php" ]]
  [[ -r /etc/controller-v8/portal.php && -s /etc/controller-v8/token ]]
  dest="$root/controller-v8"
  [[ ! -e "$dest" && ! -L "$dest" ]]
  for f in portal/*.php; do php -l "$f" >/dev/null; done
  tmp=$(mktemp -d "$root/.controller-v8.XXXXXX")
  trap 'rm -rf -- "$tmp"' EXIT
  cp portal/* "$tmp/"
  echo controller-dashboard-v8.0 > "$tmp/.controller-v8"
  chmod 755 "$tmp"
  mv -Tn "$tmp" "$dest"
  [[ ! -d "$tmp" ]]
  ;;
*) echo 'install.sh backend | portal DOCUMENT_ROOT'; exit 2;;
esac
