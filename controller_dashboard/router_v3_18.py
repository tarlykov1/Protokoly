"""Controller v3.9: join MEMO cache with user-bound asynchronous protocol reports.

Install under /webapp/app/controller_dashboard/router.py alongside both adapters.
Requests must originate from the Bitrix PHP proxy after checking group membership.
"""
import hmac
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .memo_adapter import calculate_kpis, normalize_memo_rows
from .protocol_adapter import normalize_protocol_rows

CACHE = Path(__file__).resolve().parent.parent / 'data' / 'memo_activity_cache.json'

class StartRequest(BaseModel):
    group_ids: list[int] = Field(min_length=1, max_length=100)

_REPORT_CACHE_LOCK = threading.Lock()

def _find_reusable_report(store, user_id, groups, now):
    """Reuse only same-user, exact-group, unfiltered assignment reports."""
    max_age = max(60, min(int(os.getenv('CONTROLLER_PROTOCOL_CACHE_SECONDS', '1800')), 86400))
    best, best_priority = None, None
    for file in store.RUNTIME_DIR.glob('*.json'):
        if file.name.endswith('.data.json') or file.name.startswith('.'):
            continue
        rid = file.stem
        if len(rid) != 32 or any(c not in '0123456789abcdef' for c in rid):
            continue
        try:
            meta = store.load(rid)
            params = meta.get('params') or {}
            if int(meta.get('user_id') or 0) != user_id:
                continue
            if params.get('report_type') != 'eos' or params.get('mode') != 'assignments':
                continue
            if set(map(int, params.get('group_ids') or [])) != groups:
                continue
            if any(params.get(k) for k in ('user_ids', 'event_filter', 'date_from', 'date_to')):
                continue
            status = meta.get('status')
            if status not in ('ready','queued','processing'):
                continue
            raw = meta.get('generated_at') if status == 'ready' else meta.get('created_at')
            timestamp = datetime.fromisoformat(str(raw).replace('Z','+00:00'))
            if timestamp.tzinfo is None:
                continue
            age = max(0.0, (now - timestamp.astimezone(timezone.utc)).total_seconds())
            if age > (max_age if status == 'ready' else 1800):
                continue
            if status == 'ready' and not store.data_path(rid).is_file():
                continue
            priority = (1 if status == 'ready' else 0, -age)
            if best_priority is None or priority > best_priority:
                best, best_priority = (rid,status), priority
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return best


def create_controller_dashboard_router():
    from protocol_dashboard import store, service
    router = APIRouter(prefix='/controller-dashboard-api', tags=['controller-dashboard'])

    def verify(token, user):
        expected = os.environ.get('CONTROLLER_DASHBOARD_TOKEN', '')
        if len(expected) < 32 or not token or not hmac.compare_digest(expected, token):
            raise HTTPException(403, 'Trusted Bitrix24 proxy required')
        if not user or not user.isdecimal() or int(user) <= 0:
            raise HTTPException(401, 'Bitrix24 user required')
        return int(user)

    def group_ids(header):
        if not header:
            return set()
        try:
            result = {int(s) for s in header.split(',') if s.strip()}
        except ValueError:
            raise HTTPException(400, 'Invalid protocol groups')
        if len(result) > 100 or any(g <= 0 for g in result):
            raise HTTPException(400, 'Invalid protocol groups')
        return result

    def get_report(rid, uid, allowed):
        if not rid or not allowed:
            return {'status': 'not_started'}
        if len(rid) != 32 or any(c not in '0123456789abcdef' for c in rid):
            raise HTTPException(400, 'Invalid report id')
        try:
            report = store.load(rid)
        except (FileNotFoundError, OSError, ValueError):
            return {'status': 'expired'}
        params = report.get('params') or {}
        report_groups = set(params.get('group_ids') or [])
        if (int(report.get('user_id') or 0) != uid
                or params.get('report_type') != 'eos'
                or params.get('mode') != 'assignments'
                or not report_groups
                or not report_groups.issubset(allowed)):
            raise HTTPException(403, 'Report outside authorized scope')
        state = report.get('status') or 'queued'
        result = {'status': state, 'generated_at': report.get('generated_at')}
        if state == 'ready':
            try:
                rows = store.load_data(rid).get('rows')
            except (FileNotFoundError, OSError, ValueError):
                return {'status': 'expired'}
            if not isinstance(rows, list):
                raise HTTPException(503, 'Invalid protocol report rows')
            result['items'] = normalize_protocol_rows(rows)
        return result

    @router.post('/protocol/start')
    def start(req: StartRequest,
              x_dashboard_token: str | None = Header(None),
              x_bitrix_user: str | None = Header(None),
              x_allowed_protocol_groups: str | None = Header(None)):
        uid = verify(x_dashboard_token, x_bitrix_user)
        allowed = group_ids(x_allowed_protocol_groups)
        requested = set(req.group_ids)
        if not allowed or not requested.issubset(allowed) or any(g <= 0 for g in requested):
            raise HTTPException(403, 'Protocol workgroup access required')
        with _REPORT_CACHE_LOCK:
            reused = _find_reusable_report(store, uid, requested, datetime.now(timezone.utc))
            if reused:
                rid, state = reused
                return JSONResponse({'report_id': rid, 'status': state, 'reused': True},
                                    headers={'Cache-Control': 'no-store'})
            rid = store.new_report({
                'report_type': 'eos', 'mode': 'assignments',
                'group_ids': sorted(requested), 'user_ids': [],
                'event_filter': None, 'date_from': None, 'date_to': None,
            }, uid)
            service.enqueue_dashboard(rid)
        return JSONResponse({'report_id': rid, 'status': 'queued', 'reused': False},
                            headers={'Cache-Control': 'no-store'})

    @router.get('/items')
    def items(x_dashboard_token: str | None = Header(None),
              x_bitrix_user: str | None = Header(None),
              x_allow_memo: str | None = Header(None),
              x_allowed_protocol_groups: str | None = Header(None),
              x_protocol_report: str | None = Header(None)):
        uid = verify(x_dashboard_token, x_bitrix_user)
        groups = group_ids(x_allowed_protocol_groups)
        memo_allowed = x_allow_memo == '1'
        if not groups and not memo_allowed:
            raise HTTPException(403, 'No accessible dashboard groups')
        rows, dates = [], {}
        sources = {'memo': 'not_authorized', 'protocol': 'not_authorized' if not groups else 'not_started'}
        if memo_allowed:
            try:
                cache = json.loads(CACHE.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raise HTTPException(503, 'MEMO cache unavailable')
            if int(cache.get('group_id') or 0) != int(os.getenv('CONTROLLER_MEMO_GROUP_ID', '671')):
                raise HTTPException(503, 'MEMO group mismatch')
            if not isinstance(cache.get('rows'), list):
                raise HTTPException(503, 'Invalid MEMO rows')
            rows.extend(normalize_memo_rows(cache['rows']))
            dates['memo'] = cache.get('generated_at')
            sources['memo'] = 'ready'
        if groups and x_protocol_report:
            report = get_report(x_protocol_report, uid, groups)
            sources['protocol'] = report['status']
            if report['status'] == 'ready':
                rows.extend(report['items'])
                dates['protocol'] = report.get('generated_at')
        complete = (not memo_allowed or sources['memo'] == 'ready') and (not groups or sources['protocol'] == 'ready')
        result = {
            'items': rows, 'generated_at': max((d for d in dates.values() if d), default=None),
            'generated_at_by_source': dates, 'source_status': sources,
            'sources': [k for k,v in sources.items() if v == 'ready'],
            'protocol_groups': sorted(groups), 'complete': complete,
            'kpis': calculate_kpis(rows) if complete else None,
            'limitations': ['deadline_history_not_verified', 'unread_comments_not_tracked',
                            'source_totals_incomplete' if not complete else 'no_source_gap'],
        }
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    return router
