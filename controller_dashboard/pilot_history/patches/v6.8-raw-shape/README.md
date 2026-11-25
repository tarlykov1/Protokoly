# v6.8 · raw REST и дополнительные структуры ответа (24.11.2026)

Скриншот для группы 446 показал `root=dict(size=9, known=none)`. Это **только форма ответа**, а не подтверждение, что в группе 9 поручений.

Исправлены **два отдельных диагностических файла**, а не рабочий кабинет: `probe_cli_v68.py` вызывает `fast_bitrix.call(method, params, raw=True)`; `live_probe_v68.py` принимает стандартные оболочки REST v2 и цифровые словари задач, только если каждая запись содержит валидные идентификатор и группу. Проверяется `GROUP_ID` для каждой записи (одна явно разрешённая группа). Для неизвестной структуры выводятся только заранее разрешённые названия полей и типы объектов, без значений.

Из этого патча **не** выводятся актуальный ИД, полный список задач, права контролёра или фактическая просрочка. Диагностика не подключена к FastAPI и не меняет SQLite, рабочие маршруты и систему авторизации. Поддержка обоих способов чтения комментариев (архив и чат) не меняется.

## Применение из клона Git

```bash
bash controller_dashboard/pilot_history/patches/v6.8-raw-shape/install.sh
```

Либо использовать отдельный архив `controller_v68_raw_shape_2026-11-24.zip` с идентичными модулями и автономным установщиком, не требующим Git-клона.

Установщик создаёт резервные копии в `/tmp/controller_timeline_v6_8_probe`, обновляет только два диагностических файла; перезапуск `bitrix-dashboards` **не нужен**. Вернуть версии можно вручную из `*.bak.rawshape_МЕТКА`.

## Повторная диагностика согласованной группы 446

```bash
cd /webapp/app
sudo -u dev env PYTHONPATH=/webapp/app PYTHONDONTWRITEBYTECODE=1 CONTROLLER_PILOT_ALLOWED_GROUPS=446 \
python3 -B /tmp/controller_timeline_v6_8_probe/probe_cli_v68.py --group-id 446
```

Тесты на заглушках: `pytest -q controller_dashboard/pilot_history/tests/test_live_probe_v68.py controller_dashboard/pilot_history/tests/test_raw_shape_v68.py`. Реальная проверка на сервере после обновления ещё не проводилась.

Источник библиотеки: https://github.com/leshchenko1979/fast_bitrix24/blob/master/API.md
