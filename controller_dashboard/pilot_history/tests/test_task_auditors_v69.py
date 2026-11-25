"""Read-only audit of one task's observers, without exposing personal data."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

source = Path(__file__).resolve().parents[1] / "check_task_auditors_v69.py"
spec = importlib.util.spec_from_file_location("check_task_auditors_v69", source)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def sample(auditors=None, group="734", task="77852", *, with_auditors=True):
    obj = {"id": task, "groupId": group}
    if with_auditors:
        obj["auditors"] = auditors if auditors is not None else ["1", "2", "3"]
    return {"result": {"task": obj}}


def test_overlap_only_reports_counts():
    data = m.summarize(sample(), task_id=77852, group_id=734, roster={2, 50})
    assert data["group_verified"] is True
    assert data["auditors_count"] == 3
    assert data["controller_matches"] == 1
    assert data["controller_present_in_auditors"] is True
    assert data["acl_verified_for_controller"] is False
    assert "50" not in str(data)


def test_no_roster_does_not_claim_absence():
    data = m.summarize(sample(), task_id=77852, group_id=734, roster=None)
    assert data["auditors_count"] == 3
    assert data["controller_matches"] is None
    assert data["controller_present_in_auditors"] is None


def test_missing_auditors_is_unknown_not_zero():
    data = m.summarize(sample(with_auditors=False), task_id=77852, group_id=734, roster={2})
    assert data["auditors_field_present"] is False
    assert data["auditors_count"] is None
    assert data["controller_matches"] is None


def test_empty_auditors_is_zero():
    data = m.summarize(sample(auditors=[]), task_id=77852, group_id=734, roster={2})
    assert data["auditors_count"] == 0
    assert data["controller_present_in_auditors"] is False


@pytest.mark.parametrize("task", [
    {"ID": "77852", "GROUP_ID": "734", "AUDITORS": [{"USER_ID": "11"}, {"id": 12}]},
    {"id": "77852", "groupId": "734", "auditors": ["11", 12]},
])
def test_key_formats(task):
    data = m.summarize({"task": task}, task_id=77852, group_id=734, roster={12})
    assert data["controller_matches"] == 1


@pytest.mark.parametrize("payload", [
    sample(group="446"),
    sample(task="77842"),
    {"error": "Bearer private-secret"},
    {"result": {"task": {"id": "77852", "auditors": ["1"]}}},
    {"result": [{"id": "77852"}]},
    {"result": {"task": {"id": "77852", "groupId": "734", "auditors": "private-secret"}}},
])
def test_unverified_input_fails_closed(payload):
    with pytest.raises(m.AuditorCheckError) as err:
        m.summarize(payload, task_id=77852, group_id=734, roster={1})
    assert "private-secret" not in str(err.value)


def test_async_client_uses_raw_true():
    class Client:
        async def call(self, method, params, raw=False):
            assert method == "tasks.task.get"
            assert params["taskId"] == 77852
            assert raw is True
            return sample(["11", "12"])
    result = asyncio.run(m.check(Client(), task_id=77852, group_id=734, roster={12}))
    assert result["controller_matches"] == 1


def test_sync_client_supported():
    class Client:
        def call(self, method, params, raw=False):
            return sample(["11"])
    result = asyncio.run(m.check(Client(), task_id=77852, group_id=734, roster={11}))
    assert result["controller_matches"] == 1


def test_roster_validation():
    assert m.parse_roster("") is None
    assert m.parse_roster("11,12") == {11,12}
    for invalid in ("x", "1,1", "0", "12,"):
        with pytest.raises(m.AuditorCheckError):
            m.parse_roster(invalid)
