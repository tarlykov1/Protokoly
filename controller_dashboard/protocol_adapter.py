"""Adapter for rows of protocol_dashboard reports in eos/assignments mode.

No access to runtime files or user credentials. The caller must use a report
created for the authenticated Bitrix user and verify allowed project groups.
"""
from __future__ import annotations
from typing import Any

def _date(value: Any) -> str:
    value = str(value or '').strip()
    return value[:10] if len(value) >= 10 and value[4:5] == '-' and value[7:8] == '-' else ''

def _names(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value or '').split('\n') if v.strip()]

def normalize_protocol_rows(rows: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        tid = str(row.get('task_id') or row.get('id') or '').strip()
        if not tid:
            continue
        due = _date(row.get('planned_date'))
        completed = row.get('completed') is True or str(row.get('completed')).lower() == 'true'
        raw_status = str(row.get('status') or '').strip().lower()
        stage = str(row.get('stage') or '')
        obsolete = ('неактуаль' in raw_status or 'отмен' in raw_status or
                    ('неактуаль' in stage.lower() and not completed))
        closed = _date(row.get('closed_date') or row.get('actual_date')) if completed else ''
        people = _names(row.get('executor'))
        item = {
            'id': f'protocol:{tid}', 'task_id': tid,
            'source': 'protocol', 'type': 'Протокол',
            'document': str(row.get('document') or row.get('number') or 'Протокол'),
            'event': str(row.get('event') or ''),
            'group': str(row.get('group') or ''),
            'title': str(row.get('title') or ''),
            'responsible': people[0] if len(people) == 1 else ' / '.join(people),
            'responsible_id': None, 'accomplices': [], 'assistants': [],
            'controllers': [], 'executor_names': people,
            'controller_reaction': None, 'controller_comment_count': None,
            'controller_last_comment_at': '',
            'stage': stage or 'Стадия не указана', 'due': due,
            'status': 'Неактуально' if obsolete else ('Исполнено' if completed else 'В работе'),
            'closed_at': closed,
            'closed_on_time': bool(completed and due and closed and closed <= due),
            'assigned_at': None, 'started_at': None,
            'reaction_work_minutes': None, 'reaction_in_norm': None,
            'last_activity_at': '',
            'revision_returns': int(row.get('rework_count') or 0) if str(row.get('rework_count') or '0').isdigit() else 0,
            'link': str(row.get('task_url') or ''),
            'task_leader_id': None, 'task_leader_present': False,
            'org_manager': None, 'deadline_history_available': False,
            'new_comment_since_view': None,
        }
        if tid not in out or (not out[tid]['title'] and item['title']):
            out[tid] = item
    return list(out.values())
