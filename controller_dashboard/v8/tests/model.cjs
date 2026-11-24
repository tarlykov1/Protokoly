const test=require('node:test'),assert=require('node:assert/strict'),m=require('../portal/model.js');
test('ИД, неполный срез и неизвестный срок',()=>{
 const rows=[{state:'done',closed:'2026-06-01',due:'2026-06-02'},{state:'open'},{state:'obsolete'}];
 assert.deepEqual(m.metrics(rows,true),[50,100,1]);
 assert.deepEqual(m.metrics(rows,false),[null,null,null]);
 rows[0].due=null;assert.deepEqual(m.metrics(rows,true),[50,null,1]);
 rows.push({state:null});assert.deepEqual(m.metrics(rows,true),[null,null,null]);
});
test('фильтр соисполнителя и срок без значения',()=>{
 const f={source:'',group:'',event:'',person:'тест',query:'',from:'',until:'',dueFrom:'',dueTo:''};
 const r={accomplices:['Тестовый сотрудник']};assert.ok(m.match(r,f));
 assert.ok(!m.match(r,{...f,dueFrom:'2026-03-01'}));
});
test('последний сопоставимый срез периода',()=>{
 const r=[{group:1,id:2},{group:2,id:3}], h={1:{'2026-10-01':{2:'open'},'2026-10-27':{2:'done'}},2:{'2026-10-27':{3:'open'}}};
 for(const p of ['week','month','quarter','year'])assert.equal(m.series(r,h,[1,2],p)[0][1],50);
});
