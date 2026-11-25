#!/usr/bin/env bash
# Update the existing portal page, keeping its Bitrix wrapper and local settings.
set -euo pipefail
src=$(cd "$(dirname "$0")" && pwd)
dir=${BITRIX_ROOT:-/home/bitrix/www}/controller
test -f "$dir/cabinet.php" && test -f "$dir/index.php" || { echo 'Не найден установленный кабинет /controller/' >&2; exit 1; }
files=(common.php data.php view.php ui.js style.css)
for f in "${files[@]}"; do test -f "$dir/$f"; done
for f in common.php data.php view.php; do php -l "$src/portal/$f"; done
umask 077
backup=$(mktemp /root/controller-portal-XXXXXXXX.tar.gz)
tar -czf "$backup" -C "$dir" "${files[@]}"
echo "Откат: tar -xzf '$backup' -C '$dir'"
trap 'tar -xzf "$backup" -C "$dir"' ERR
for f in "${files[@]}"; do install -m 0644 "$src/portal/$f" "$dir/$f"; done
echo 'Кабинет обновлён.'
