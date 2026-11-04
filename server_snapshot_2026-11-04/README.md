# Рабочие исходники дашбордов Битрикс24 — 04.11.2026

Источник: предоставленные архивы `22archive.tar.gz` (портал Битрикс24) и `webapp.zip` (Python-сервер).

**Статус: НЕПОЛНАЯ загрузка / промежуточная ветка. Не сливать в main и не разворачивать.**

Фактически загруженные модули: `python/protocol_dashboard/{__init__,schema,settings,adapter,service}.py` и `python/controller_dashboard/__init__.py`.

Исходный локальный очищенный комплект включает 47 файлов: Python `controller_dashboard`, `protocol_dashboard`, `memo_activity_dashboard.py`, шаблоны и Excel-генераторы; PHP/JS/CSS `controller-dashboard`, `dashboard/assistant`, `protocol-dashboard`, `memo-activity`. Остальные файлы ещё НЕ записаны в GitHub.

**Безопасность:** серверные конфигурации, кэш, служебные файлы и резервные копии исключены. В `python/protocol_dashboard/settings.py` убран жёстко заданный резервный токен: теперь `PROTOCOL_DASHBOARD_TOKEN` требуется из среды. Это целенаправленное отличие от серверного источника.

Нельзя считать эту ветку полноценной резервной копией рабочего контура до загрузки остальных модулей и проверки полного сопоставления файлов. Старое приложение `Protokoly` не заменено.
