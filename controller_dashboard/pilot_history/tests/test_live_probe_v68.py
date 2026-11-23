import asyncio
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('probe', Path(__file__).parents[1] / 'live_probe_v68.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def run(coro):
    return asyncio.run(coro)


async def sample(method, params):
    assert method == 'tasks.task.list'
    assert params['filter'] == {'GROUP_ID': 123}
    assert params['start'] == 0
    assert 'DESCRIPTION' not in params['select']
    return {'tasks': [{'id': '1', 'groupId': '123', 'status': 5, 'deadline': '2026-11-23'}, {'ID': '2', 'GROUP_ID': 123, 'STATUS': 2}]}


def test_allowed_group_read_only_aggregate():
    res = run(probe.probe_group(sample, group_id=123, allowed_groups=frozenset({123})))
    assert res['first_page_count'] == 2
    assert res['status_codes'] == {'2': 1, '5': 1}
    assert res['deadlines_present'] == 1
    assert res['kpi_calculated'] is False
    assert res['acl_verified_for_controller'] is False
    assert res['data_saved'] is False
    assert 'task_id' not in str(res)


def test_no_call_for_unapproved_group():
    async def forbidden(*args):
        raise AssertionError('Unexpected network call')
    with pytest.raises(probe.ProbeError):
        run(probe.probe_group(forbidden, group_id=999, allowed_groups=frozenset({123})))


def test_reject_wrong_group_or_missing_group():
    async def wrong(*args):
        return {'tasks': [{'id': '10', 'groupId': 124, 'status': 5}]}
    async def missing(*args):
        return {'tasks': [{'id': '10', 'status': 5}]}
    for call in (wrong, missing):
        with pytest.raises(probe.ProbeError):
            run(probe.probe_group(call, group_id=123, allowed_groups=frozenset({123})))


def test_reject_malformed_response():
    async def broken(*args):
        return {'result': 'not a list'}
    with pytest.raises(probe.ProbeError):
        run(probe.probe_group(broken, group_id=123, allowed_groups=frozenset({123})))


def test_reject_oversize_page():
    async def huge(*args):
        return [{'id': i+1, 'groupId': 123} for i in range(51)]
    with pytest.raises(probe.ProbeError):
        run(probe.probe_group(huge, group_id=123, allowed_groups=frozenset({123})))


def test_error_is_sanitized():
    async def err(*args):
        raise RuntimeError('Bearer confidential-secret-in-exception')
    with pytest.raises(probe.ProbeError, match='REST-запрос') as ei:
        run(probe.probe_group(err, group_id=123, allowed_groups=frozenset({123})))
    assert 'confidential-secret-in-exception' not in str(ei.value)
