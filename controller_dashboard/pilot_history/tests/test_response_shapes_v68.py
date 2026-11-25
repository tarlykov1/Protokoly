"""One-page v2 response-envelope checks without exposing raw task details."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

p = Path(__file__).parents[1] / 'live_probe_v68.py'
spec = importlib.util.spec_from_file_location('live_probe_v68_shapes', p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fetch(payload):
    async def read(_method, _params):
        return payload
    return asyncio.run(m.probe_group(read, group_id=446, allowed_groups=frozenset({446})))


def task():
    return {'id': '1', 'groupId': '446', 'status': '5', 'deadline': '2026-11-24'}


@pytest.mark.parametrize('payload', [
    [task()],
    {'tasks': [task()]},
    {'result': {'tasks': [task()]}},
    {'result': [task()]},
    {'data': {'result': {'tasks': [task()]}}},
    {'response': {'result': {'tasks': [task()]}}},
])
def test_supported_response_envelopes(payload):
    result = fetch(payload)
    assert result['first_page_count'] == 1
    assert result['status_codes'] == {'5': 1}
    assert result['deadlines_present'] == 1


def test_unknown_shape_reports_only_whitelisted_structure():
    with pytest.raises(m.ProbeError) as err:
        fetch({'token-supersensitive': 'do-not-leak', 'result': {'items': [{'title': 'do-not-leak'}]}})
    message = str(err.value)
    assert 'root=dict(' in message
    assert 'level1(result)=dict(' in message
    assert 'known=items' in message
    assert 'token-supersensitive' not in message
    assert 'do-not-leak' not in message


def test_error_response_does_not_expose_content():
    with pytest.raises(m.ProbeError) as err:
        fetch({'error': 'private-secret'})
    assert 'private-secret' not in str(err.value)
    assert 'признак ошибки' in str(err.value)


def test_wrong_group_fails_closed():
    with pytest.raises(m.ProbeError):
        fetch({'data': {'tasks': [{'id': '1', 'groupId': '447', 'status': 5}]}})


def test_v3_items_not_silently_accepted():
    with pytest.raises(m.ProbeError):
        fetch({'result': {'items': [task()]}})
