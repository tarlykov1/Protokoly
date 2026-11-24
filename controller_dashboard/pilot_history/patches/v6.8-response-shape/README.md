# v6.8: диагностика неизвестной структуры tasks.task.list

Проверка группы 446 завершилась ошибкой разбора ответа, а не сетевым исключением. Обновлён `live_probe_v68.py` в корне `pilot_history`: распаковка известных оболочек REST v2 (`tasks`, `result.tasks`, `result`, `data.result.tasks`, `response.result.tasks`); при других форматах выводятся только типы контейнеров, их размеры и признак заранее разрешённых ключей. Нет вывода конфиденциальных значений и полного REST-ответа.

Тесты: `tests/test_response_shapes_v68.py` (10), `tests/test_live_probe_v68.py` (6). Пользовательский сайт, БД, системные службы и `main.py` не изменяются.

Для применения из Git-клона `tarlykov1/Protokoly`, находясь в корне репозитория:
```bash
bash controller_dashboard/pilot_history/patches/v6.8-response-shape/install.sh
```
Установщик копирует только `live_probe_v68.py` в `/tmp/controller_timeline_v6_8_probe/`, создаёт backup, проверяет синтаксис без записи в `__pycache__`. При отсутствии прав записи в `/tmp` – выполнять установку соответствующим владельцем или с `sudo`.

Диагностика реальной, отдельно одобренной группы 446:
```bash
cd /webapp/app
sudo -u dev env PYTHONPATH=/webapp/app PYTHONDONTWRITEBYTECODE=1 CONTROLLER_PILOT_ALLOWED_GROUPS=446 \
  python3 -B /tmp/controller_timeline_v6_8_probe/probe_cli_v68.py --group-id 446
```

Если структура остаётся неизвестной – зафиксировать только диагностическую строку `root=...; level1=...`, НЕ печатать исходный ответ или токены. Результат запроса не может сам по себе подтверждать ACL контролёра или корректный расчёт исполнительской дисциплины.
