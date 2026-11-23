import json
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from timeline_v6 import (_api_result, _legacy_comments, _chat_comments, _chat_id,
                         _comment_ids, _merge_comments, router)


def test_normalization_and_no_cross_source_dedup():
    legacy = _legacy_comments({'result': [{'ID': '55', 'AUTHOR_ID': '8',
                                           'POST_MESSAGE': 'Старый текст', 'POST_DATE': '2026-01-01T12:00:00+03:00'}]})
    new, cursor = _chat_comments({'result': {'messages': [
        {'id':55,'author_id':8,'date':'2026-10-02T12:00:00+03:00','text':'Новый текст','params':[]},
        {'id':40,'author_id':0,'text':'Вступил в чат','params':{'CODE':['CHAT_JOIN']}},
    ]}})
    assert cursor == 40
    both = _merge_comments(legacy, new)
    assert len(both) == 2
    assert [(x['source'], x['id']) for x in both] == [('legacy','55'),('chat','55')]
    assert _chat_id({'result': {'task': {'chatId': 287}}}) == 287
    assert _chat_id({'result': {'item': {'chat': {'id': 287}}}}) == 287
    assert _comment_ids([{'field':'COMMENT_EDIT','old_value':'88','new_value':'89'},
                         {'field':'AUDITORS','old_value':'13','new_value':'14'}]) == [88,89]


def client_with_adapter(tmp_path,monkeypatch,adapter):
    import sqlite3, types
    db=tmp_path/'pilot.sqlite'
    with sqlite3.connect(db) as con:
        con.execute('CREATE TABLE pilot_history_events (id integer, task_id integer, field text, occurred_at text, actor_id integer, value_json text)')
        con.execute('INSERT INTO pilot_history_events VALUES (1,100193,?,?,?,?)',
                    ('COMMENT','2026-08-01T10:00:00+03:00',8,json.dumps({'new':'101'})))
    monkeypatch.setenv('CONTROLLER_PILOT_DB_PATH',str(db))
    monkeypatch.setenv('CONTROLLER_PILOT_TOKEN','safe-pilot-token')
    mod=types.ModuleType('tools'); modtools=types.ModuleType('tools.tools')
    modtools.fast_bitrix=adapter; mod.tools=modtools
    monkeypatch.setitem(sys.modules,'tools',mod)
    monkeypatch.setitem(sys.modules,'tools.tools',modtools)
    api=FastAPI();api.include_router(router)
    return TestClient(api),db


def test_both_methods_are_called_and_ids_preserved(tmp_path,monkeypatch):
    calls=[]
    class Adapter:
        async def call(self,name,params,**kwargs):
            calls.append((name,params,kwargs))
            if name == 'task.commentitem.getlist':
                return {'result':[{'ID':'101','AUTHOR_ID':'8','POST_MESSAGE':'Старый комментарий','POST_DATE':'2026-08-01T10:00:00+03:00'}]}
            if name == 'tasks.task.get':
                return {'result':{'task':{'chatId':2000}}}
            if name == 'im.dialog.messages.get':
                if 'FIRST_ID' in params: return {'result':{'messages':[]}}
                return {'result':{'messages':[{'id':101,'author_id':9,'text':'Новый чат','date':'2026-10-01T11:00:00+03:00','params':[]}], 'users':[]}}
            raise AssertionError(name)
    api,db=client_with_adapter(tmp_path,monkeypatch,Adapter())
    original=db.read_bytes()
    path='/controller-pilot-test/history/100193/comments'
    assert api.get(path).status_code==401
    assert not calls
    assert api.get(path,headers={'Authorization':'Bearer invalid'}).status_code==403
    assert not calls
    r=api.get(path,headers={'Authorization':'Bearer safe-pilot-token'})
    assert r.status_code==200,r.text
    j=r.json()
    assert j['counts']=={'legacy':1,'chat':1}
    assert [(c['source'],c['id'],c['text']) for c in j['comments']] == [
        ('legacy','101','Старый комментарий'),('chat','101','Новый чат')]
    assert db.read_bytes()==original
    assert 'task.commentitem.getlist' in [x[0] for x in calls]
    assert 'im.dialog.messages.get' in [x[0] for x in calls]
    assert any(x[0]=='task.commentitem.getlist' and x[2]=={'raw': True} and x[1]==[100193, {'ID':'asc'}, {}] for x in calls)
    assert any(x[0]=='im.dialog.messages.get' and x[2]=={} for x in calls)


def test_one_source_failure_does_not_hide_other_source(tmp_path,monkeypatch):
    class Adapter:
        async def call(self,name,params,**kwargs):
            if name=='task.commentitem.getlist': raise RuntimeError('legacy disabled')
            if name=='task.commentitem.get':
                return {'result':{'ID':'101','POST_MESSAGE':'Архив по ID','AUTHOR_ID':'2'}}
            if name=='tasks.task.get': return {'result':{'task':{'chatId':150}}}
            if name=='im.dialog.messages.get': raise RuntimeError('im scope denied')
            raise AssertionError(name)
    api,_=client_with_adapter(tmp_path,monkeypatch,Adapter())
    result=api.get('/controller-pilot-test/history/100193/comments',headers={'Authorization':'Bearer safe-pilot-token'}).json()
    assert result['partial'] is True
    assert result['counts']=={'legacy':1,'chat':0}
    assert result['comments'][0]['text']=='Архив по ID'
    assert len(result['warnings'])==2


def test_unrelated_task_not_available(tmp_path,monkeypatch):
    class Adapter:
        async def call(self,name,params,**kwargs): raise AssertionError('should not call')
    api,_=client_with_adapter(tmp_path,monkeypatch,Adapter())
    response=api.get('/controller-pilot-test/history/334455/comments',headers={'Authorization':'Bearer safe-pilot-token'})
    assert response.status_code==404
