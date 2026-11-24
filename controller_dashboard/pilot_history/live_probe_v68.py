"""Single-page, read-only Bitrix24 task diagnostics for ONE approved group.

This is a server-operator diagnostic, NOT a controller-facing API. Never infer
access permissions from an integration service account or calculate KPI/ID here.
No data is persisted and no titles/descriptions/comments are returned.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

TaskCall = Callable[[str, dict[str, Any]], Awaitable[Any]]

# Legacy tasks.task.list (REST v2). Do not silently substitute the incompatible v3 API.
SELECT = ('ID', 'GROUP_ID', 'STATUS', 'DEADLINE', 'RESPONSIBLE_ID', 'CLOSED_DATE')
MAX_PAGE = 50  # REST v2 returns a maximum of 50 per page by default


class ProbeError(RuntimeError):
    """Safe diagnostic message; no raw API error text/credentials."""


def _shape_summary(payload: Any) -> str:
    """Return structure metadata only, never response values or arbitrary keys."""
    allowed = ('tasks', 'result', 'data', 'response', 'items', 'error')
    def summary(value: Any) -> str:
        typ = type(value).__name__
        if isinstance(value, dict):
            flags = ','.join(key for key in allowed if key in value) or 'none'
            return f'dict(size={len(value)}, known={flags})'
        if isinstance(value, (list, tuple)):
            return f'{typ}(size={len(value)})'
        return typ

    parts = ['root=' + summary(payload)]
    current = payload
    for depth in range(3):
        if not isinstance(current, dict):
            break
        child_key = next((key for key in ('result', 'data', 'response', 'tasks') if key in current), None)
        if child_key is None:
            break
        current = current[child_key]
        parts.append(f'level{depth + 1}({child_key})=' + summary(current))
    return '; '.join(parts)


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Unwrap known REST-v2 result envelopes; refuse unknown/v3 shapes."""
    data: Any = payload
    for _ in range(4):
        if isinstance(data, list):
            break
        if not isinstance(data, dict):
            raise ProbeError('Неизвестный формат ответа tasks.task.list; ' + _shape_summary(payload))
        if 'error' in data:
            raise ProbeError('REST вернул признак ошибки (содержание скрыто); ' + _shape_summary(payload))
        if 'tasks' in data:
            data = data['tasks']
        elif 'result' in data:
            data = data['result']
        elif 'data' in data:
            data = data['data']
        elif 'response' in data:
            data = data['response']
        else:
            raise ProbeError('Неизвестный формат ответа tasks.task.list; ' + _shape_summary(payload))
    if not isinstance(data, list):
        raise ProbeError('В ответе отсутствует ожидаемый список задач; ' + _shape_summary(payload))
    if not all(isinstance(item, dict) for item in data):
        raise ProbeError('В ответе есть запись не в формате объекта; ' + _shape_summary(payload))
    return data


def _value(row: dict[str, Any], name: str) -> Any:
    return row.get(name) if name in row else row.get(name.lower()) if name.lower() in row else row.get(''.join(w.title() if i else w.lower() for i, w in enumerate(name.split('_'))))


def _id(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str) and not value.strip().isdigit():
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


async def probe_group(call: TaskCall, *, group_id: int, allowed_groups: frozenset[int], page_size: int = MAX_PAGE) -> dict[str, Any]:
    """Read only the first legacy REST page from explicitly permitted group.

    Fail closed on wrong/missing group IDs or unexpected response formats. The
    result contains counts only; it deliberately does not claim to be the full
    group, the current controller's access scope, or execution-discipline KPI.
    """
    if not isinstance(group_id, int) or group_id <= 0 or group_id not in allowed_groups:
        raise ProbeError('Группа не включена в явный список разрешённых для диагностики')
    if not isinstance(page_size, int) or page_size != MAX_PAGE:
        raise ProbeError('Диагностика поддерживает только одну страницу из 50 задач')
    params = {
        'filter': {'GROUP_ID': group_id},
        'select': list(SELECT),
        'order': {'ID': 'ASC'},
        'start': 0,
    }
    try:
        result = await call('tasks.task.list', params)
    except Exception as exc:
        # Exception type is safe to show; never display raw exception messages,
        # which may contain a URL, headers or REST response content.
        raise ProbeError(
            f'REST-запрос tasks.task.list завершился ошибкой ({type(exc).__name__})'
        ) from None
    rows = _rows(result)
    if len(rows) > MAX_PAGE:
        raise ProbeError('Ответ длиннее одной страницы: возможен неограниченный запрос')
    counts = Counter()
    missing_status = 0
    deadlines_present = 0
    for row in rows:
        actual_group = _id(_value(row, 'GROUP_ID'))
        if actual_group != group_id:
            raise ProbeError('У ответа отсутствует проверенная принадлежность к запрошенной группе')
        if _id(_value(row, 'ID')) is None:
            raise ProbeError('В ответе есть задача без корректного ID')
        status = _value(row, 'STATUS')
        if status is None or str(status).strip() == '':
            missing_status += 1
        else:
            # Status is an unverified REST code: keep code only, not KPI interpretation.
            counts[str(status)] += 1
        if _value(row, 'DEADLINE'):
            deadlines_present += 1
    return {
        'ok': True,
        'group_id': group_id,
        'checked_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source': 'tasks.task.list / REST v2 / first page only',
        'first_page_count': len(rows),
        'possibly_more_pages': len(rows) == MAX_PAGE,
        'status_codes': dict(sorted(counts.items())),
        'missing_status': missing_status,
        'deadlines_present': deadlines_present,
        'kpi_calculated': False,
        'acl_verified_for_controller': False,
        'data_saved': False,
        'notice': 'Это диагностические агрегаты одной разрешённой группы, не отчёт об ИД, просрочке или правах контролёра.',
    }
