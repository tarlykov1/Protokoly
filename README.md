# Protocol Management System

Внутреннее серверное веб-приложение для управления протоколами, поручениями и будущим созданием задач в коробочной версии Битрикс24. Протокол и поручение являются первичными доменными объектами; задачи Битрикс24 создаются на их основании.

## Архитектура

- `app/db/models` — SQLAlchemy 2 доменная модель.
- `app/services/task_planning` — формирование внутреннего плана задач без вызова Битрикс24.
- `app/services/ai` — независимый AI-слой, отключённый по умолчанию.
- `app/parsers` — расширяемый каркас парсеров DOCX.
- `app/main.py` и `app/web/templates` — минимальный серверный интерфейс FastAPI/Jinja2.
- `prototype/index.html` — автономный HTML-прототип для демонстрации бизнес-сценария.

## Требования

Python 3.12, PostgreSQL для целевого окружения, SQLite допустим для локальной проверки, Docker/Docker Compose на следующих этапах.

## Установка и запуск

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
```

## Миграции

```bash
alembic upgrade head
alembic revision --autogenerate -m "message"
```

## Тесты и линтер

```bash
pytest
ruff check .
```

## Переменные окружения

- `DATABASE_URL` — строка подключения SQLAlchemy, по умолчанию `sqlite:///./protocols.db`.
- `AI_ENABLED=false`
- `AI_PROVIDER=rule_based`
- `AI_ALLOW_EXTERNAL=false`
- `AI_MODEL=`
- `AI_API_KEY=`

Не добавляйте `.env`, токены, реальные протоколы, локальные БД и персональные данные в Git.

## Текущие ограничения

Первый этап не подключается к реальному Битрикс24, не использует внешние AI-модели, не реализует авторизацию и полный DOCX-парсер. Каркас не блокирует добавление этих функций.

## Дальнейший план

1. Расширить редактор протокола и поручения.
2. Добавить импорт DOCX с сохранением исходных файлов.
3. Реализовать порт и адаптер Битрикс24.
4. Добавить синхронизацию и журнал интеграционных операций.
5. Подключить безопасные AI-провайдеры через независимый слой.

## Разработка и Pull Request

1. Работа выполняется в feature-ветке.
2. Для законченного этапа создаётся pull request.
3. Если pull request уже открыт, новые коммиты добавляются в эту же ветку.
4. Новый pull request для той же ветки не создаётся.
5. Пока CI не прошёл, pull request не сливается.
6. После зелёного CI pull request можно переводить из Draft в Ready for review.
7. После проверки pull request сливается.
8. Следующий функциональный этап начинается только после слияния предыдущего либо в отдельной согласованной ветке.

## DOCX import MVP

The application supports a staged DOCX import workflow for real protocol drafts without creating Bitrix24 tasks.

1. Open `/protocols/import`, choose a project, upload a `.docx`, and optionally select a parser.
2. `POST /protocols/import/preview` stores the file under `var/imports` (outside `static`), validates extension, MIME type, ZIP signature, size, safe generated filename, and SHA-256 checksum, then creates an `ImportSession`.
3. `/protocols/import/{session_id}/preview` shows parser confidence, protocol metadata, sections, tasks, assignees, deadlines, warnings, errors, duplicate hints, and editable JSON payload.
4. `POST /protocols/import/{session_id}/update` saves manual corrections in `ImportSession.parsed_payload`; the original DOCX is not changed.
5. `POST /protocols/import/{session_id}/reparse` reruns parsing with explicit confirmation and keeps prior payload in parse history.
6. `POST /protocols/import/{session_id}/confirm` creates `Protocol`, `ProtocolSection`, `ProtocolTask`, and assignment records, stores the source file path, and marks the session confirmed.
7. `POST /protocols/import/{session_id}/cancel` cancels the session without creating core protocol entities.
8. `/protocols/imports` lists import sessions with filters by project, status, and parser type.

Supported MVP patterns include regular paragraphs, Word headings, uppercase section names, numbered and bulleted-like tasks, DOCX tables with `Поручение / Ответственный / Срок`, absolute Russian dates, relative/periodic deadlines, and raw assignee strings resolved against the local employee directory where possible.

Parsers are registered in `ParserRegistry`: `UniversalProtocolParser`, `MemoParser`, `CeoProtocolParser`, and `DeputyCeoProtocolParser`. To add a parser, implement the shared `ProtocolParser` interface (`supports`, `confidence`, `parse`) and register it in `ParserRegistry`.

Temporary import sessions expire after `IMPORT_SESSION_TTL_HOURS` (default `24`). Run cleanup with:

```bash
python -m app.cli.cleanup_imports
```

MVP limitations: Bitrix24 task creation is intentionally disabled; preview editing uses JSON payload editing rather than a full spreadsheet UI; date inference avoids inventing concrete dates for relative deadlines.
