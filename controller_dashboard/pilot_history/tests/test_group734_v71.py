from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import collect_group734_v71 as collector
import group734_v71 as snapshot


@pytest.fixture(autouse=True)
def reset_technical_logins(monkeypatch):
    collector.TECHNICAL_LOGINS = frozenset()
    yield
    collector.TECHNICAL_LOGINS = frozenset()


def make_roster():
    return [{"ID": str(i), "PROPERTY_306": {str(i): str(v)}} for i, v in enumerate(range(100, 108), 1)]


def task(i, *, group=734, status=5, deadline="2026-11-25T18:00:00+03:00", auditors=None):
    result = {"id": str(i), "groupId": str(group), "status": status, "deadline": deadline}
    if auditors is not None:
        result["auditors"] = [str(x) for x in auditors]
    return result


class Client:
    def __init__(self, tasks, *, total=None, fail=None, roster=None):
        self.tasks = tasks
        self.roster = roster if roster is not None else make_roster()
        self.total = total
        self.calls = []
        self.fail = fail

    async def call(self, method, params, raw=False):
        assert raw is True
        self.calls.append((method, params))
        if self.fail == method:
            raise RuntimeError("API-TOKEN-DO-NOT-LEAK")
        if method == "lists.get.iblock.type.id":
            return {"result": "lists"}
        if method == "lists.field.get":
            return {"result": {"PROPERTY_306": {
                "FIELD_ID": "PROPERTY_306", "TYPE": "S:employee"}}}
        if method == "lists.element.get":
            return {"result": self.roster[params["start"]:params["start"] + 50],
                    "total": len(self.roster)}
        if method == "user.get":
            uid = params["ID"]
            names = {106: "fictional-admin-a", 107: "fictional-admin-b"}
            return {"result": [{"ID": uid, "LOGIN": names.get(uid, "controller" + str(uid))}]}
        if method == "tasks.task.list":
            start = params["start"]
            rows = self.tasks[start:start + 50]
            response = {"result": {"tasks": rows},
                        "total": self.total if self.total is not None else len(self.tasks)}
            if start + 50 < len(self.tasks):
                response["next"] = start + 50
            return response
        raise AssertionError(method)


NOW = datetime(2026, 11, 24, 15, 0, tzinfo=ZoneInfo("Europe/Moscow"))


def run(client, max_pages=20):
    return asyncio.run(collector.collect(client, max_pages=max_pages, now=NOW))


def test_full_scan_exact_counts_and_tech_exclusion(monkeypatch):
    monkeypatch.setenv("CONTROLLER_PILOT_TECH_LOGINS", "fictional-admin-a,fictional-admin-b")
    collector.TECHNICAL_LOGINS = frozenset({"fictional-admin-a", "fictional-admin-b"})
    tasks = [task(i, auditors=[100, 106]) for i in range(1, 50)]
    tasks += [task(50, status=3, deadline="2026-11-23T18:00:00+03:00", auditors=[107])]
    tasks += [task(51, status=2, deadline="2026-11-25T18:00:00+03:00", auditors=[101])]
    data = run(Client(tasks))
    assert data["pagination_complete"] is True
    assert data["pages_checked"] == 2
    assert data["tasks_checked"] == 51
    assert data["status_codes"] == {"2": 1, "3": 1, "5": 49}
    assert data["overdue_open_count"] == 1
    assert data["due_in_7_days_count"] == 1
    assert data["tasks_with_list91_auditor"] == 51
    assert data["technical_exclusions_verified"] is True
    assert data["tasks_with_nontechnical_roster_auditor"] == 50
    assert data["list91_employee_count"] == 8
    assert "100" not in json.dumps(snapshot.validate_snapshot(data))


def test_nontechnical_unavailable_if_user_id_lookup_fails(monkeypatch):
    monkeypatch.setenv("CONTROLLER_PILOT_TECH_LOGINS", "fictional-admin-a,fictional-admin-b")
    collector.TECHNICAL_LOGINS = frozenset({"fictional-admin-a", "fictional-admin-b"})
    result = run(Client([task(1, auditors=[101])], fail="user.get"))
    assert result["technical_exclusions_verified"] is False
    assert result["tasks_with_nontechnical_roster_auditor"] is None
    assert result["tasks_with_list91_auditor"] == 1


def test_missing_auditors_explicitly_unknown():
    result = run(Client([task(1)]))
    assert result["tasks_with_list91_auditor"] == 0
    assert result["tasks_with_unknown_auditors"] == 1
    assert result["no_deadline"] == 0


def test_incomplete_pagination_is_explicit():
    rows = [task(i, auditors=[100]) for i in range(1, 102)]
    result = run(Client(rows), max_pages=1)
    assert result["pagination_complete"] is False
    assert result["tasks_checked"] == 50
    assert result["pages_checked"] == 1


def test_unknown_status_refuses_to_store_snapshot():
    with pytest.raises(collector.CollectionError):
        run(Client([task(1, status="X", auditors=[101])]))


def test_cross_group_rows_fail_closed():
    with pytest.raises(collector.CollectionError, match="вне группы"):
        run(Client([task(1, group=735, auditors=[100])]))


def test_bad_roster_binding_fails():
    c = Client([task(1)])
    c.roster = [{"ID": "1", "PROPERTY_306": {"a": "Иванов"}}]
    with pytest.raises(collector.CollectionError, match="поле сотрудника"):
        run(c)


def test_all_pages_have_at_most_50():
    result = run(Client([task(i, auditors=[100]) for i in range(1, 101)]))
    assert result["pagination_complete"] is True
    assert result["pages_checked"] == 2
    assert result["tasks_checked"] == 100


def test_missing_deadline_not_zeroed_or_counted_overdue():
    result = run(Client([task(1, status=2, deadline=None, auditors=[100])]))
    assert result["deadlines_present"] == 0
    assert result["no_deadline"] == 1
    assert result["overdue_open_count"] == 0


def test_snapshot_read_only_and_atomic_write(tmp_path):
    data = run(Client([task(1, auditors=[100])]))
    target = tmp_path / "pilot_summary.json"
    assert not target.exists()
    snapshot.atomic_write(data, target)
    assert target.is_file()
    assert target.stat().st_mode & 0o777 == 0o600
    original = target.read_bytes()
    loaded = snapshot.read_snapshot(target)
    assert loaded["tasks_checked"] == 1
    assert loaded["kpi_calculated"] is False
    assert target.read_bytes() == original
    assert "100" not in original.decode()


def test_snapshot_rejects_forged_coverage(tmp_path):
    data = run(Client([task(1, auditors=[100])]))
    data["status_codes"]["5"] = 9
    with pytest.raises(snapshot.SnapshotError):
        snapshot.atomic_write(data, tmp_path / "fake.json")
    assert not (tmp_path / "fake.json").exists()


def test_snapshot_rejects_symlink(tmp_path):
    data = run(Client([task(1, auditors=[100])]))
    outside = tmp_path / "outside.json"
    outside.write_text("private", encoding="utf8")
    symlink = tmp_path / "bad.json"
    symlink.symlink_to(outside)
    with pytest.raises(snapshot.SnapshotError):
        snapshot.atomic_write(data, symlink)
    assert outside.read_text(encoding="utf8") == "private"


def test_error_sanitized():
    with pytest.raises(collector.CollectionError) as err:
        run(Client([task(1)], fail="tasks.task.list"))
    assert "API-TOKEN-DO-NOT-LEAK" not in str(err.value)


def test_api_auth_and_static_assets(tmp_path):
    import group734_routes_v71
    from fastapi import APIRouter, FastAPI, HTTPException
    from fastapi.testclient import TestClient

    root = tmp_path
    (root / "data").mkdir()
    for name in ("dashboard_group734_v71.html", "dashboard_group734_v71.js", "dashboard_group734_v71.css"):
        (root / name).write_text("test", encoding="utf8")
    payload = run(Client([task(1, auditors=[100])]))
    snapshot.atomic_write(payload, root / "data" / "group734_summary_v71.json")
    router = APIRouter(prefix="/controller-pilot-test")
    def authorize(token):
        if token != "Bearer test-token":
            raise HTTPException(401, "Unauthorized")
    group734_routes_v71.register_routes(router, authorize, root)
    app = FastAPI()
    app.include_router(router)
    api = TestClient(app)
    path = "/controller-pilot-test/overview/group734/data"
    assert api.get(path).status_code == 401
    response = api.get(path, headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    assert response.json()["tasks_checked"] == 1
    assert api.get("/controller-pilot-test/overview/group734/").status_code == 200
    assert api.get("/controller-pilot-test/overview/group734/app.js").status_code == 200


def test_no_auto_write_and_no_auto_http():
    source = (ROOT / "group734_routes_v71.py").read_text(encoding="utf8")
    assert "tasks.task.list" not in source
    assert "atomic_write(" not in source
    assert "read_snapshot(" in source


def test_installer_and_rollback_keep_pilot_sqlite(tmp_path):
    import subprocess

    root = tmp_path / "controller_dashboard_test"
    root.mkdir()
    (root / "data").mkdir()
    baseline = (b'from fastapi import APIRouter\n'
                b'router = APIRouter(prefix="/controller-pilot-test")\n'
                b'@router.get("/overview/data")\n'
                b'def get_data(): return {}\n')
    (root / "timeline_v6.py").write_bytes(baseline)
    (root / "overview_v67.html").write_text("v6.7 page", encoding="utf8")
    (root / "data" / "pilot.sqlite").write_bytes(b"history-unchanged")
    (root / "data" / "pilot_comment_snapshots.sqlite").write_bytes(b"comments-unchanged")
    env = dict(os.environ, CONTROLLER_PILOT_APP_DIR=str(root))
    proc = subprocess.run(["bash", str(ROOT / "install.sh")], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    updated = (root / "timeline_v6.py").read_text(encoding="utf8")
    assert "V71_GROUP734_ROUTES_BEGIN" in updated
    assert (root / "group734_v71.py").exists()
    assert (root / "data" / "pilot.sqlite").read_bytes() == b"history-unchanged"
    second = subprocess.run(["bash", str(ROOT / "install.sh")], env=env, capture_output=True, text=True)
    assert second.returncode != 0
    backup = next(root.glob("timeline_v6.py.bak.v7_1_*"))
    stamp = backup.name.split("bak.v7_1_")[-1]
    undone = subprocess.run(["bash", str(ROOT / "rollback.sh"), stamp], env=env,
                            capture_output=True, text=True)
    assert undone.returncode == 0, undone.stdout + undone.stderr
    assert (root / "timeline_v6.py").read_bytes() == baseline
    assert not (root / "group734_v71.py").exists()
    assert (root / "data" / "pilot.sqlite").read_bytes() == b"history-unchanged"
    assert (root / "data" / "pilot_comment_snapshots.sqlite").read_bytes() == b"comments-unchanged"
