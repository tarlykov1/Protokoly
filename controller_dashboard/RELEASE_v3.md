# Кабинет контролёра — установочный комплект v3 (27.10.2026)

Подготовлен отдельный ZIP `controller_dashboard_bitrix24_v3_test.zip` с файлами PHP + Python; код проверен `php -l` и `python3 -m py_compile`. ZIP **не коммитится в Git как бинарная сборка**, он выдаётся как проверенный архив в разговоре.

Схема: `/controller-dashboard/index.php` на портале Битрикс24 с `prolog_before.php` и проверкой `UserToGroupTable` по группе 671 → `api.php` → `/controller-dashboard-api/items` на Python с обязательным серверным `CONTROLLER_DASHBOARD_TOKEN` и `X-Bitrix-User`. JS не получает секреты; кэш `data/memo_activity_cache.json` проверяется на `group_id = 671`. Текущие МЕМО и протоколы не заменяются.

Состав архива: `bitrix/controller-dashboard/{index.php,api.php,guard.php,config.php,dashboard.html}`, `python/controller_dashboard/{__init__.py,router.py,memo_adapter.py}`, `python/templates/controller_dashboard.html`, README.md, MANIFEST_SHA256.json.

Ограничения: **только МЕМО**, протоколы не подключены. Историю переноса сроков и непрочитанные комментарии пока нельзя рассчитать достоверно. Потребуется дополнительная проверка безопасности инфраструктуры и фактических прав контролёров перед широким развёртыванием.

Порядок установки описан в README внутри ZIP. Перед копированием обязательно сохранить текущий Python-модуль, проверить установку секрета в среде PHP и systemd, а также запретить прямой доступ к порту FastAPI извне. Код PHP/Python будет переноситься в Git отдельными коммитами; наличие этой заметки не означает, что весь архив находится в Git.
