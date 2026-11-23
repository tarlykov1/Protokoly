const test=require('node:test');
const assert=require('node:assert/strict');
const {mergedTimelineEntries}=require('../timeline_v6.js');

test('first captured version of linked legacy comment is embedded, not duplicated',()=>{
 const hist=[{field:'COMMENT',new_value:'701617',occurred_at:'2026-09-01'}];
 const archive=[{archive_kind:'snapshot',comment_source:'legacy',comment_id:'701617',archive_version:1},
 {archive_kind:'snapshot',comment_source:'legacy',comment_id:'701617',archive_version:2},
 {archive_kind:'not_returned',comment_source:'legacy',comment_id:'701617'}];
 const merged=mergedTimelineEntries(hist,archive);
 assert.equal(merged.length,3);
 assert.equal(merged.filter(x=>x.archive_kind==='snapshot').length,1);
 assert.equal(merged.filter(x=>x.archive_kind==='not_returned').length,1);
});
test('unlinked and chat snapshots stay as independent observation entries',()=>{
 const hist=[{field:'COMMENT',new_value:123}];
 const archive=[{archive_kind:'snapshot',comment_source:'chat',comment_id:'123',archive_version:1},
 {archive_kind:'snapshot',comment_source:'legacy',comment_id:'456',archive_version:1}];
 assert.equal(mergedTimelineEntries(hist,archive).length,3);
});
test('other task actions do not accidentally consume archive snapshots',()=>{
 const hist=[{field:'DEADLINE',new_value:123}];
 const archive=[{archive_kind:'snapshot',comment_source:'legacy',comment_id:'123',archive_version:1}];
 assert.equal(mergedTimelineEntries(hist,archive).length,2);
});
