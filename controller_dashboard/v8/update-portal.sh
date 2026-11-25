#!/usr/bin/env bash
set -euo pipefail
src=$(cd "$(dirname "$0")" && pwd)
dir=${BITRIX_ROOT:-/home/bitrix/www}/controller
[[ -f "$dir/cabinet.php" && -f "$dir/index.php" ]] || { echo 'Не найден установленный кабинет /controller/' >&2; exit 1; }
files=(common.php data.php api.php model.js registry.js ui.js style.css view.php)
for f in common.php data.php api.php view.php; do php -l "$src/portal/$f"; done
umask 077
backup=$(mktemp -d "${BACKUP_DIR:-/root}/controller-portal-XXXXXXXX")
rollback="$backup/rollback.sh"
existing=()
for f in "${files[@]}"; do
    test -f "$src/portal/$f"
    if [[ -f "$dir/$f" ]]; then existing+=("$f"); elif [[ "$f" != registry.js ]]; then echo "Отсутствует $dir/$f" >&2; exit 1; fi
done
tar -czf "$backup/portal.tar.gz" -C "$dir" "${existing[@]}"
{
    echo '#!/usr/bin/env bash'
    echo 'set -eu'
    printf 'tar -xzf %q -C %q\n' "$backup/portal.tar.gz" "$dir"
    if [[ ! -f "$dir/registry.js" ]]; then printf 'rm -f -- %q\n' "$dir/registry.js"; fi
} > "$rollback"
echo "Откат: bash '$rollback'"
trap 'bash "$rollback"' ERR
for f in "${files[@]}"; do install -m 0644 "$src/portal/$f" "$dir/$f"; done
echo 'Кабинет обновлён.'
