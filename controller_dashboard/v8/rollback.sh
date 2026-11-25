#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
backend) dest=/opt/controller-v8;;
portal) root=$(realpath -e "${2:?DOCUMENT_ROOT}"); dest="$root/controller-v8";;
*) exit 2;;
esac
[[ ! -L "$dest" && "$(cat "$dest/.controller-v8")" == controller-dashboard-v8.0 ]]
if [[ "$1" == backend ]]; then
  systemctl disable --now controller-v8.service
  rm /etc/systemd/system/controller-v8.service
  systemctl daemon-reload
fi
if [[ "$1" == portal ]]; then
  # Remove only the files owned by this release.
  for file in index.php view.php api.php common.php data.php model.js registry.js ui.js style.css .controller-v8; do rm -f -- "$dest/$file"; done
  rmdir "$dest"
else
  mv -T "$dest" "$dest.withdrawn.$(date +%s)"
fi
