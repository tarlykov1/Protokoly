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
test('неизвестный срок и состояние не превращаются в нулевую просрочку',()=>{
 const now=Date.parse('2026-11-25T09:00:00+03:00'), due=m.zones['Просрочено'];
 assert.equal(due({state:'open',due:null},now),null);
 assert.equal(m.overdueWeek({state:'open',due:'2026-11-17T23:50:00+03:00'},now),true);
 assert.equal(m.overdueWeek({state:'open',due:'2026-11-18T00:01:00+03:00'},now),false);
 assert.equal(m.overdueWeek({state:'done',due:null},now),false);
 assert.equal(m.upcoming({state:'open',due:'2026-11-30T23:59:00+03:00'},now,5),true);
 assert.equal(m.exactCount([{state:'done'},{state:null}],r=>due(r,now)),null);
 assert.equal(m.exactCount([],r=>due(r,now)),0);
});
test('CSV экранирует текст из задач и не выполняет формулы',()=>{
 assert.equal(m.csvCell('=1+1'),'"\'=1+1"');
 assert.equal(m.csvCell('Он сказал "да"'),'"Он сказал ""да"""');
 assert.equal(m.csvCell(null),'"Нет данных"');
 assert.equal(m.csvCell('  @external'),'"\'  @external"');
});
test('детализация закрытых по срокам не приписывает отсутствующей дате своевременность',()=>{
 const task={state:'done',due:'2026-11-23T17:00:00+03:00',closed:'2026-11-24T11:00:00+03:00'};
 assert.deepEqual(m.stageDeadlines([task],Date.now()).map(r=>r[1]),[1,0]);
 assert.deepEqual(m.stageDeadlines([task,{...task,closed:null}],Date.now()).map(r=>r[1]),[null,null]);
});

test('частичный охват не скрывает доказанные результаты и не меняет знаменатель молча',()=>{
 const sample=[{state:'done',due:'2026-01-10',closed:'2026-01-12'},{state:'open'},{state:null},{state:'obsolete'}];
 const c=m.kpiCoverage(sample);
 assert.deepEqual(c.execution,{yes:1,unknown:1,total:4});
 assert.equal(c.active,2);assert.equal(c.discipline,50);assert.equal(c.onTime,0);
 assert.equal(m.kpiCoverage([{state:null}]).discipline,null);
 assert.equal(m.kpiCoverage([{state:'done',due:null,closed:null}]).onTime,null);
});
