import asyncio
import importlib.util
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('raw_shape_probe', ROOT / 'live_probe_v68.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
spec2 = importlib.util.spec_from_file_location('raw_shape_cli', ROOT / 'probe_cli_v68.py')
cli = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(cli)

def run(x):
    return asyncio.run(x)

def one_task(i=1, group=446):
    return {'id': str(i), 'groupId': str(group), 'status': '5', 'deadline': '2026-11-24'}

def fetch(payload):
    async def caller(method, params):
        assert method == 'tasks.task.list'
        assert params['filter'] == {'GROUP_ID': 446}
        return payload
    return run(probe.probe_group(caller, group_id=446, allowed_groups=frozenset({446})))

@pytest.mark.parametrize('result', [
    [one_task()],
    {'tasks': [one_task()]},
    {'result': {'tasks': [one_task()]}},
    {'result': [one_task()]},
    {'data': {'result': {'tasks': [one_task()]}}},
    {'response': {'result': {'tasks': [one_task()]}}},
    {'1001': one_task(1001)},
    {'0': one_task(1001), '1': one_task(1002)},
    {1001: one_task(1001)},
])
def test_accepted_envelopes_and_numeric_mapping(result):
    data = fetch(result)
    assert data['ok'] is True
    assert data['first_page_count'] in (1, 2)
    assert data['kpi_calculated'] is False
    assert data['data_saved'] is False

def test_single_task_dict_is_not_mistaken_for_list():
    with pytest.raises(probe.ProbeError) as err:
        fetch({'id':'1', 'groupId':'446', 'status':'5', 'title':'secret-title'})
    assert 'secret-title' not in str(err.value)
    assert 'task_fields=' in str(err.value)

def test_mapping_non_numeric_keys_not_accepted():
    with pytest.raises(probe.ProbeError):
        fetch({'a': one_task()})

def test_mapping_incomplete_record_not_accepted():
    with pytest.raises(probe.ProbeError):
        fetch({'1': {'status':'5', 'groupId':'446'}})

def test_mapping_wrong_group_fails_closed():
    with pytest.raises(probe.ProbeError):
        fetch({'1': one_task(group=447)})

def test_unexpected_response_never_displays_values_or_keys():
    secret='secret-personal-text-or-token'
    with pytest.raises(probe.ProbeError) as err:
        fetch({secret:{'title':secret, 'groupId':446}})
    assert secret not in str(err.value)
    assert 'root=dict(size=1' in str(err.value)

def test_raw_sync():
    class FakeClient:
        def call(self, method, params, raw=False):
            assert raw is True
            assert method == 'tasks.task.list'
            return {'result': {'tasks': [one_task()]}}
    assert 'tasks' in run(cli.call_client(FakeClient(), 'tasks.task.list', {}))['result']

def test_raw_async():
    class FakeClient:
        async def call(self, method, params, raw=False):
            assert raw is True
            return {'result':{'tasks':[]}}
    assert 'result' in run(cli.call_client(FakeClient(), 'tasks.task.list', {}))

def test_client_without_call_rejected():
    with pytest.raises(cli.ProbeError):
        run(cli.call_client(object(), 'tasks.task.list', {}))
