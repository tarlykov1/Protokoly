'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {cleanBitrixText,formatDateValue} = require('../timeline_v6.js');

test('Bitrix paragraphs, user mentions and blank lines are human readable',()=>{
  const input='[P]В работе.[/P][P]План согласован[/P][P][/P][P]Просьба продлить срок[/P]';
  assert.equal(cleanBitrixText(input),'В работе.\n\nПлан согласован\n\nПросьба продлить срок');
});
test('Task mention shows saved display name without service markup',()=>{
  assert.equal(cleanBitrixText('[USER=6855]Серегин Андрей Николаевич[/USER], вы назначены исполнителем.'),
    'Серегин Андрей Николаевич, вы назначены исполнителем.');
});
test('Formatting tags and entities are converted without HTML injection',()=>{
  assert.equal(cleanBitrixText('[B]Важно[/B] &amp; срочно &lt;script&gt;'),
    'Важно & срочно <script>');
  // Only a plain string is returned, which the UI inserts using textContent.
});
test('Unknown markup is not silently discarded',()=>{
  assert.equal(cleanBitrixText('Событие [UNKNOWN=5]значение[/UNKNOWN]'),'Событие [UNKNOWN=5]значение[/UNKNOWN]');
});
test('Unicode, list items, URL labels and attachments',()=>{
  assert.equal(cleanBitrixText('[LIST][*]Один[*]Два[/LIST] [URL=https://example.com]ссылка[/URL] [ATTACH=5]'),
    '• Один\n• Два ссылка [Вложение]');
});
test('Empty or non-string values and dates keep existing behavior',()=>{
  assert.equal(cleanBitrixText(null),'');
  assert.equal(cleanBitrixText(123),'123');
  assert.equal(formatDateValue('1795446000'),'23.11.2026, 18:00');
});
