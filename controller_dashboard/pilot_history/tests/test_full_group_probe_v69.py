"""Read-only pagination invariants (no corporate API or credentials)."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("full_probe_v69", ROOT / "full_group_probe_v69.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def run(call, *, max_pages=10):
    return asyncio.run(probe.probe_full_group(
        call, group_id=446, allowed_groups=frozenset({446}), max_pages=max_pages,
    ))


def rows(first, count=50, group=446, status=5):
    return [{
        "id": str(i),
        "groupId": str(group),
        "status": str(status),
        "deadline": "2026-11-24",
    } for i in range(first, first + count)]


def test_two_pages_aggregate_and_completion():
    calls = []
    async def call(method, params):
        assert method == "tasks.task.list"
        calls.append(params["start"])
        if params["start"] == 0:
            return {"result": {"tasks": rows(1)}, "next": 50, "total": 53}
        return {"result": {"tasks": rows(51, 3, status=2)}, "total": 53}
    result = run(call)
    assert calls == [0, 50]
    assert result["pagination_complete"] is True
    assert result["pages_checked"] == 2
    assert result["tasks_checked"] == 53
    assert result["status_codes"] == {"2": 3, "5": 50}
    assert result["deadlines_present"] == 53
    assert result["kpi_calculated"] is False
    assert result["acl_verified_for_controller"] is False
    assert result["data_saved"] is False


def test_cap_is_explicit_and_never_claims_completeness():
    async def call(_, params):
        return {"result": {"tasks": rows(1)}, "next": 50}
    result = run(call, max_pages=1)
    assert result["tasks_checked"] == 50
    assert result["limit_reached"] is True
    assert result["pagination_complete"] is False
    assert result["next_start"] == 50


def test_group_mismatch_is_rejected():
    async def call(*args):
        return {"result": {"tasks": rows(1, 1, group=447)}}
    with pytest.raises(probe.ProbeError, match="разрешённой группы"):
        run(call)


def test_cross_page_duplicate_is_rejected():
    async def call(_, params):
        if params["start"] == 0:
            return {"result": {"tasks": rows(1)}, "next": 50}
        return {"result": {"tasks": rows(50, 1)}}
    with pytest.raises(probe.ProbeError, match="Повторяющиеся"):
        run(call)


@pytest.mark.parametrize("nxt", [True, 20, -1, "secret", {}, 0])
def test_bad_next_is_rejected(nxt):
    async def call(*args):
        return {"result": {"tasks": rows(1)}, "next": nxt}
    with pytest.raises(probe.ProbeError):
        run(call)


def test_next_with_short_page_rejected():
    async def call(*args):
        return {"result": {"tasks": rows(1, 2)}, "next": 50}
    with pytest.raises(probe.ProbeError, match="неполной странице"):
        run(call)


def test_rejected_group_causes_no_request():
    called = False
    async def call(*args):
        nonlocal called
        called = True
        return {"result": {"tasks": []}}
    with pytest.raises(probe.ProbeError):
        asyncio.run(probe.probe_full_group(call, group_id=446, allowed_groups=frozenset({447})))
    assert called is False


def test_page_bound_rejected_before_network():
    async def call(*args):
        raise AssertionError("Must not call")
    for max_pages in (0, 11, -1, True):
        with pytest.raises(probe.ProbeError):
            run(call, max_pages=max_pages)


def test_raw_error_message_is_not_leaked():
    async def call(*args):
        raise RuntimeError("SECRET-TOKEN-DO-NOT-SHOW")
    with pytest.raises(probe.ProbeError) as err:
        run(call)
    assert "SECRET-TOKEN-DO-NOT-SHOW" not in str(err.value)


def test_exactly_fifty_without_next_is_last_page():
    async def call(*args):
        return {"result": {"tasks": rows(1)}, "total": 50}
    result = run(call)
    assert result["tasks_checked"] == 50
    assert result["pagination_complete"] is True
