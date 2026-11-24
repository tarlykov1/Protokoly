import asyncio
import importlib.util
from pathlib import Path

import pytest
spec = importlib.util.spec_from_file_location('roster',Path(__file__).resolve().parents[1] / 'roster_probe_v70.py')
roster = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roster)

SCHEMA = {'result': {'PROPERTY_78': {'FIELD_ID': 'PROPERTY_78', 'NAME': 'Сотрудник', 'TYPE': 'S:employee', 'PROPERTY_USER_TYPE': 'employee'}, 'PROPERTY_79': {'FIELD_ID':'PROPERTY_79','NAME':'Должность','TYPE':'S'}}}

class Client:
    def __init__(self, schemas=SCHEMA, rows=None, task=None):
        self.calls=[]
        self.schemas=schemas
        self.rows=rows or [{'ID':'123','PROPERTY_78':{'42':'999','43':'150'}}, {'ID':'124','PROPERTY_78':{'44':'250'}}]
        self.task=task or {'result':{'task':{'id':'77852','groupId':'734','auditors':['150','550','300','20']}}}
    async def call(self,name,params,raw=False):
        self.calls.append((name,params,raw))
        assert raw is True
        if name=='lists.get.iblock.type.id':
            return {'result':'lists'}
        if name=='lists.field.get':
            return self.schemas
        if name=='tasks.task.get':
            return self.task
        if name=='lists.element.get':
            return {'result':self.rows[params['start']:params['start']+50], 'total':len(self.rows)}
        raise AssertionError(name)

def test_detects_matching_controller():
    client=Client()
    result=asyncio.run(roster.probe(client,list_id=83,task_id=77852,group_id=734))
    assert result['controller_in_task'] is True
    assert result['matched_controller_count']==1
    assert result['controllers_found_in_list']==3
    assert result['task_auditors_count']==4
    assert result['list_scan_complete'] is True
    assert all(c[2] is True for c in client.calls)
    assert '999' not in str(result)
    assert result['data_saved'] is False
    assert result['acl_verified_for_controller'] is False

def test_requires_single_employee_field():
    client=Client(schemas={'result': {**SCHEMA['result'], 'PROPERTY_80': {'FIELD_ID':'PROPERTY_80','NAME':'Контролёр','TYPE':'S:employee'}}})
    r=asyncio.run(roster.probe(client,list_id=83,task_id=77852,group_id=734))
    assert r['status']=='needs_field_selection'
    assert not any(n=='tasks.task.get' for n,_,_ in client.calls)
    with pytest.raises(roster.ProbeError):
        asyncio.run(roster.probe(client,list_id=83,task_id=77852,group_id=734,field_id='PROPERTY_79'))

def test_missing_property_doesnt_fabricate_controller():
    client=Client(rows=[{'ID':'1'}])
    r=asyncio.run(roster.probe(client,list_id=83,task_id=77852,group_id=734))
    assert r['controller_in_task'] is False
    assert r['controllers_found_in_list']==0

def test_mismatched_group_fails_closed():
    client=Client(task={'result':{'task':{'id':'77852','groupId':'999','auditors':['150']}}})
    with pytest.raises(roster.ProbeError):
        asyncio.run(roster.probe(client,list_id=83,task_id=77852,group_id=734))

def test_complete_pagination_fifty_plus_one():
    rows=[{'ID':str(i),'PROPERTY_78':{'22':str(i)}} for i in range(1,52)]
    client=Client(rows=rows)
    r=asyncio.run(roster.probe(client,list_id=83,task_id=77852,group_id=734))
    assert r['list_items_read']==51
    assert r['list_scan_complete'] is True
    assert len([c for c in client.calls if c[0]=='lists.element.get'])==2

def test_unconfirmed_data_not_leaked():
    class Bad(Client):
        async def call(self,name,params,raw=False):
            if name=='lists.field.get':
                raise RuntimeError('Bearer SECRET-ADDRESS')
            return await super().call(name,params,raw)
    with pytest.raises(roster.ProbeError) as ei:
        asyncio.run(roster.probe(Bad(),list_id=83,task_id=77852,group_id=734))
    assert 'SECRET-ADDRESS' not in str(ei.value)

def test_employee_property_parser_never_uses_keys_as_ids():
    assert roster.parse_employee_property({'442':'150','443':'250'})=={150,250}
    with pytest.raises(roster.ProbeError):
        roster.parse_employee_property({'442':'Иванов Иван'})

@pytest.mark.parametrize('value',[False,0,'',None,'-3','77a'])
def test_invalid_id(value):
    assert roster.positive_id(value) is None
