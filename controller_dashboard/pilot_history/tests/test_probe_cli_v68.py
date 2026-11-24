"""Regression checks for the FastBitrix object adapter used by v6.8 CLI."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('controller_probe_cli_v68', ROOT / 'probe_cli_v68.py')
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def run(coroutine):
    return asyncio.run(coroutine)


def test_sync_client_method_returns_dict():
    class FakeClient:
        def __init__(self):
            self.requests = []

        def call(self, method, params, *, raw):
            assert raw is True
            self.requests.append((method, params))
            return {'tasks': []}

    client = FakeClient()
    result = run(cli.call_client(client, 'tasks.task.list', {'filter': {'GROUP_ID': 456}}))
    assert result == {'tasks': []}
    assert client.requests == [('tasks.task.list', {'filter': {'GROUP_ID': 456}})]


def test_async_client_method_returns_dict():
    class FakeClient:
        async def call(self, method, params, *, raw):
            assert raw is True
            return {'tasks': [{'id': 7, 'groupId': 456}]}

    result = run(cli.call_client(FakeClient(), 'tasks.task.list', {}))
    assert result['tasks'][0]['id'] == 7


def test_reject_client_without_call_method():
    with pytest.raises(cli.ProbeError, match=r'\.call'):
        run(cli.call_client(object(), 'tasks.task.list', {}))
