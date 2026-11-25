import json
import os
import sqlite3
import stat
import sys
import types
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comment_archive_v66 import read_archive, save_observation
from timeline_v6 import router


def fixture_history(tmp_path, monkeypatch):
    history = tmp_path / 'pilot.sqlite'
    with sqlite3.connect(history) as c:
        c.execute('CREATE TABLE pilot_history_events (id INTEGER,task_id INTEGER,field TEXT,occurred_at TEXT,actor_id INTEGER,value_json TEXT)')
        c.execute('INSERT INTO pilot_history_events VALUES (1,100193,?,?,?,?)',
                  ('COMMENT', '2026-09-24T13:47:00+03:00', 2891, json.dumps({'new':'688732'})))
    archive = tmp_path / 'snapshots.sqlite'
    monkeypatch.setenv('CONTROLLER_PILOT_COMMENT_ARCHIVE_DB_PATH', str(archive))
    monkeypatch.setenv('CONTROLLER_PILOT_DB_PATH', str(history))
    monkeypatch.setenv('CONTROLLER_PILOT_TOKEN', 'pilot-only-token')
    return history,archive


def comment(source='legacy', cid='688732', body='Первый текст', **overrides):
    return {'source':source,'id':cid,'author_id':'2891','author_name':'Николай',
            'created_at':'2026-09-24T13:47:00+03:00', 'text':body,
            'edited':None,'deleted':None, **overrides}


def test_read_is_pure_and_first_save_is_private(tmp_path,monkeypatch):
    history,archive=fixture_history(tmp_path, monkeypatch)
    original=history.read_bytes()
    empty=read_archive(history,100193)
    assert empty['initialized'] is False
    assert not archive.exists()
    saved=save_observation(history,100193,[comment(),comment(source='chat',cid='688732',body='Другой источник')],
                           {'legacy':'complete','chat':'complete'})
    assert saved['new_comments']==2
    assert saved['new_versions']==2
    assert history.read_bytes()==original
    assert stat.S_IMODE(os.stat(archive).st_mode)==0o600
    d=read_archive(history,100193)
    assert d['stats']=={'comments':2,'versions':2,'not_returned':0}
    assert {(i['source'],i['comment_id']) for i in d['items']}=={('chat','688732'),('legacy','688732')}
    assert len([x for x in d['archive_events'] if x['kind']=='snapshot'])==2


def test_versions_idempotence_and_no_false_missing(tmp_path,monkeypatch):
    history,archive=fixture_history(tmp_path,monkeypatch)
    ready={'legacy':'complete','chat':'complete'}
    save_observation(history,100193,[comment('legacy'),comment('chat',cid='20',body='Чат')],ready)
    repeated=save_observation(history,100193,[comment('legacy'),comment('chat',cid='20',body='Чат')],ready)
    assert (repeated['new_versions'],repeated['unchanged'])==(0,2)
    # A partial/unavailable response NEVER implies that the chat comment was deleted.
    changed=save_observation(history,100193,[comment(body='Вторая редакция')],
                             {'legacy':'complete','chat':'unavailable'})
    assert changed['new_versions']==1
    assert changed['now_not_returned']==0
    assert read_archive(history,100193)['stats']=={'comments':2,'versions':3,'not_returned':0}
    # A complete archive enumeration without a previously visible entry records only 'not_returned'.
    missing=save_observation(history,100193,[],{'legacy':'complete','chat':'partial'})
    assert missing['now_not_returned']==1
    d=read_archive(history,100193)
    assert d['stats']['not_returned']==1
    assert next(i for i in d['items'] if i['source']=='legacy')['versions'][-1]['body']=='Вторая редакция'
    assert any(e['kind']=='not_returned' and e['source']=='legacy' for e in d['archive_events'])
    # A partial read with zero comments does not remove more items or generate false events.
    partial=save_observation(history,100193,[],{'legacy':'partial','chat':'partial'})
    assert partial['now_not_returned']==0
    restored=save_observation(history,100193,[comment(body='Вторая редакция')],{'legacy':'complete','chat':'unavailable'})
    assert restored['returned']==1
    assert restored['new_versions']==0
    assert any(e['kind']=='returned' for e in read_archive(history,100193)['archive_events'])


def test_edited_status_is_new_version_even_if_text_unchanged(tmp_path,monkeypatch):
    history,_=fixture_history(tmp_path,monkeypatch)
    save_observation(history,100193,[comment(source='chat',edited=False)],{'chat':'complete','legacy':'partial'})
    r=save_observation(history,100193,[comment(source='chat',edited=True)],{'chat':'complete','legacy':'partial'})
    assert r['new_versions']==1
    item=read_archive(history,100193)['items'][0]
    assert item['versions'][0]['edited']==0
    assert item['versions'][1]['edited']==1


def test_refuses_to_touch_pilot_history(tmp_path,monkeypatch):
    history,_=fixture_history(tmp_path,monkeypatch)
    monkeypatch.setenv('CONTROLLER_PILOT_COMMENT_ARCHIVE_DB_PATH',str(history))
    initial=history.read_bytes()
    import pytest
    with pytest.raises(ValueError):
        save_observation(history,100193,[comment()],{'legacy':'complete','chat':'unavailable'})
    assert history.read_bytes()==initial
    other=tmp_path/'other.sqlite'
    with sqlite3.connect(other) as c:
        c.execute('CREATE TABLE pilot_history_events(id INTEGER)')
    monkeypatch.setenv('CONTROLLER_PILOT_COMMENT_ARCHIVE_DB_PATH',str(other))
    with pytest.raises(ValueError):
        save_observation(history,100193,[comment()],{'legacy':'complete','chat':'unavailable'})
    with sqlite3.connect(other) as c:
        assert c.execute("SELECT name FROM sqlite_master WHERE name='comment_archive_items'").fetchone() is None


def test_http_auth_opt_in_and_legacy_still_works(tmp_path,monkeypatch):
    history,archive=fixture_history(tmp_path,monkeypatch)
    calls=[]
    class Adapter:
        async def call(self,name,params,**opts):
            calls.append((name,opts))
            if name=='task.commentitem.getlist':
                assert opts=={'raw':True}
                return {'result':[{'ID':'688732','AUTHOR_ID':'2891','AUTHOR_NAME':'Николай','POST_MESSAGE':'Старый комментарий','POST_DATE':'2026-09-24T13:47:00+03:00'}]}
            if name=='tasks.task.get':
                return {'result':{'task':{'id':100193}}}
            raise AssertionError(name)
    tools=types.ModuleType('tools')
    tools_tools=types.ModuleType('tools.tools')
    tools_tools.fast_bitrix=Adapter()
    tools.tools=tools_tools
    monkeypatch.setitem(sys.modules,'tools',tools)
    monkeypatch.setitem(sys.modules,'tools.tools',tools_tools)
    app=FastAPI()
    app.include_router(router)
    client=TestClient(app)
    endpoint='/controller-pilot-test/history/100193'
    assert client.post(endpoint+'/comments/snapshot').status_code==401
    assert not calls
    assert client.get(endpoint+'/comment-archive').status_code==401
    assert not archive.exists()
    hdr={'Authorization':'Bearer pilot-only-token'}
    before=client.get(endpoint+'/comment-archive',headers=hdr)
    assert before.status_code==200
    assert before.json()['initialized'] is False
    assert not calls
    post=client.post(endpoint+'/comments/snapshot',headers=hdr)
    assert post.status_code==200,post.text
    assert post.json()['saved']['new_comments']==1
    assert post.json()['saved']['source_status']=={'legacy':'complete','chat':'unavailable'}
    assert post.json()['fetched']['counts']['legacy']==1
    assert client.get(endpoint+'/comment-archive',headers=hdr).json()['stats']['versions']==1
    assert history.exists()
    assert client.post('/controller-pilot-test/history/99/comments/snapshot',headers=hdr).status_code==404
