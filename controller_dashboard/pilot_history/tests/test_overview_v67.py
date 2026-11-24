import sqlite3
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import overview_v67
import timeline_v6


def fixture_db(tmp_path):
    db=tmp_path/'pilot.sqlite'
    con=sqlite3.connect(db)
    con.execute('CREATE TABLE pilot_history_events (id INTEGER PRIMARY KEY, task_id INTEGER, occurred_at TEXT, field TEXT, actor_id INTEGER)')
    con.executemany('INSERT INTO pilot_history_events(task_id,occurred_at,field,actor_id) VALUES (?,?,?,?)',[
        (100193,'2026-11-23T11:20:00+03:00','COMMENT',14),
        (100193,'2026-11-23T11:23:00+03:00','DEADLINE',14),
        (102280,'2026-11-15T10:00:00+03:00','NEW',16),
    ])
    con.commit()
    con.close()
    archive=tmp_path/'pilot_comment_snapshots.sqlite'
    ac=sqlite3.connect(archive)
    ac.execute('CREATE TABLE comment_archive_items (task_id INTEGER, comment_id TEXT)')
    ac.executemany('INSERT INTO comment_archive_items VALUES (?,?)',[(100193,'9'),(100193,'10')])
    ac.commit()
    ac.close()
    return db,archive


def test_overview_aggregates_readonly(tmp_path):
    db,archive=fixture_db(tmp_path)
    before=(db.read_bytes(),archive.read_bytes())
    data=overview_v67.overview_data(db,archive)
    assert data['totals']=={
        'tasks_in_history':2,'history_events':3,'deadline_changes':1,
        'comment_actions':1,'saved_comments':2}
    assert len(data['tasks'])==2
    row=next(x for x in data['tasks'] if x['task_id']==100193)
    assert row['event_count']==2
    assert row['deadline_changes']==1 and row['saved_comments']==2
    assert not data['kpi_availability']['execution_discipline']
    assert db.read_bytes()==before[0] and archive.read_bytes()==before[1]


def test_overview_missing_archive_does_not_create(tmp_path):
    db,_=fixture_db(tmp_path)
    absent=tmp_path/'nonexistent.sqlite'
    data=overview_v67.overview_data(db,absent)
    assert not absent.exists()
    assert data['totals']['saved_comments']==0
    assert data['tasks'][0]['saved_comments']==0


def test_route_is_authorized_and_static_page_available(tmp_path,monkeypatch):
    db,archive=fixture_db(tmp_path)
    monkeypatch.setenv('CONTROLLER_PILOT_TOKEN','test-token-only')
    monkeypatch.setenv('CONTROLLER_PILOT_DB_PATH',str(db))
    monkeypatch.setenv('CONTROLLER_PILOT_COMMENT_ARCHIVE_DB_PATH',str(archive))
    app=FastAPI()
    app.include_router(timeline_v6.router)
    client=TestClient(app)
    path='/controller-pilot-test/overview/data'
    assert client.get(path).status_code==401
    assert client.get(path,headers={'Authorization':'Bearer incorrect'}).status_code==403
    response=client.get(path,headers={'Authorization':'Bearer test-token-only'})
    assert response.status_code==200
    assert response.json()['totals']['history_events']==3
    assert client.get('/controller-pilot-test/overview/').status_code==200
    assert client.get('/controller-pilot-test/overview/overview_v67.js').status_code==200
    assert client.get('/controller-pilot-test/overview/overview_v67.css').status_code==200
    assert client.get('/controller-pilot-test/history/100193/events',headers={'Authorization':'Bearer test-token-only'}).status_code==200


def test_limit_and_missing_or_nonconforming_schema(tmp_path):
    db,archive=fixture_db(tmp_path)
    assert overview_v67.overview_data(db,archive,limit=1)['capped'] is True
    for invalid in [0,251]:
        import pytest
        with pytest.raises(ValueError):
            overview_v67.overview_data(db,archive,limit=invalid)
