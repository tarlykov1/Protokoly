const {test}=require('node:test');
const assert=require('node:assert/strict');
const {dateObject,formatDateValue,eventDate,eventValue,peopleDiff,isTimeField,typeName} = require('../timeline_v6.js');

test('Unix seconds format as Moscow dates for deadline',()=>{
 assert.equal(eventValue('DEADLINE',1785510000),'31.07.2026, 18:00');
 assert.equal(eventValue('DEADLINE','1795446000'),'23.11.2026, 18:00');
 assert.equal(eventValue('DEADLINE',1795446000000),'23.11.2026, 18:00');
});
test('numeric comment/status/user IDs remain numeric',()=>{
 assert.equal(eventValue('COMMENT',701620),'701620');
 assert.equal(eventValue('STATUS',2),'2');
 assert.equal(eventValue('AUDITORS',8598),'8598');
 assert.equal(dateObject('701620'),null);
 assert.equal(isTimeField('COMMENT'),false);
});
test('ISO event timestamp respects timezone offset',()=>{
 assert.equal(eventDate('2026-10-23T10:58:16+03:00'),'23.10.2026, 10:58 МСК');
 assert.equal(eventDate('2026-10-23T07:58:16Z'),'23.10.2026, 10:58 МСК');
});
test('Local unzoned datetime uses Moscow local not browser timezone',()=>{
 assert.equal(formatDateValue('2026-11-23 18:00:00'),'23.11.2026, 18:00');
});
test('Added auditors detected exactly, regardless of reorder',()=>{
 const delta=peopleDiff('2708,3485,3492','2708,3485,3492,8598');
 assert.deepEqual(delta.added,['8598']);
 assert.deepEqual(delta.removed,[]);
 assert.deepEqual(peopleDiff('1,2','2,1').added,[]);
});
test('Russian human event labels',()=>{
 assert.equal(typeName('COMMENT_EDIT'),'Редактирование комментария');
 assert.equal(typeName('UF_CRM_TASK_DELETED'),'Удаление связи с CRM');
});
