const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {JSDOM} = require('jsdom');
const script = readFileSync('app/web/static/js/protocol-document-ux.js', 'utf8');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function fixture(fetch) {
  const dom = new JSDOM(`<section class="protocol-document" data-protocol-id="1" data-version="1">
    <span data-protocol-field="title">Original</span><span data-protocol-field="number">42</span>
    <div class="document-signatory" data-signatory-id="17"><span data-signatory-field="role">Chair</span><span data-signatory-field="name_snapshot">Name</span></div>
    <button data-protocol-print>Print</button><button data-protocol-pdf>PDF</button>
  </section>`, {runScripts: 'outside-only', url: 'http://localhost/protocols/1'});
  dom.window.fetch = fetch;
  dom.window.alert = () => {};
  dom.window.eval(script);
  return dom;
}
function edit(dom, selector, value) {
  const element = dom.window.document.querySelector(selector);
  element.dispatchEvent(new dom.window.MouseEvent('dblclick', {bubbles: true}));
  const control = element.querySelector('input');
  control.value = value;
  control.blur();
  return element;
}

test('inline edits are serialized and advance the saved version', async () => {
  const requests = [];
  let active = 0, maxActive = 0;
  const dom = fixture(async (_, options) => {
    active++; maxActive = Math.max(maxActive, active);
    requests.push(JSON.parse(options.body));
    await delay(20); active--;
    return {ok: true, json: async () => ({saved: true, version: requests.length + 1})};
  });
  try {
    edit(dom, '[data-protocol-field="title"]', 'New title');
    edit(dom, '[data-protocol-field="number"]', '43');
    await delay(100);
    assert.equal(maxActive, 1);
    assert.deepEqual(requests.map(r => r.version), [1, 2]);
    assert.equal(dom.window.document.querySelector('.protocol-document').dataset.version, '3');
  } finally { dom.window.close(); }
});

test('signatory edit patches a stable ID without replacing the list', async () => {
  let request;
  const dom = fixture(async (_, options) => {
    request = JSON.parse(options.body);
    return {ok: true, json: async () => ({version: 2})};
  });
  try {
    edit(dom, '[data-signatory-field="role"]', 'Secretary');
    await delay(10);
    assert.deepEqual(request.signatory_updates, [{id: 17, role: 'Secretary'}]);
    assert.equal(request.signatories, undefined);
  } finally { dom.window.close(); }
});

test('unchanged blur does not write', async () => {
  let calls = 0;
  const dom = fixture(async () => { calls++; });
  try {
    edit(dom, '[data-protocol-field="title"]', 'Original');
    await delay(10);
    assert.equal(calls, 0);
  } finally { dom.window.close(); }
});

test('save conflict retains typed text and blocks later overwrites', async () => {
  let calls = 0;
  const dom = fixture(async () => { calls++; return {ok: false, json: async () => ({detail: 'Conflict'})}; });
  try {
    const title = edit(dom, '[data-protocol-field="title"]', 'Keep this draft');
    await delay(10);
    assert.equal(title.textContent, 'Keep this draft');
    edit(dom, '[data-protocol-field="number"]', '44');
    await delay(10);
    assert.equal(calls, 1);
  } finally { dom.window.close(); }
});

test('printing waits for pending writes', async () => {
  let saved = false, printed = false;
  const dom = fixture(async () => { await delay(20); saved = true; return {ok: true, json: async () => ({version: 2})}; });
  try {
    dom.window.print = () => { assert.equal(saved, true); printed = true; };
    edit(dom, '[data-protocol-field="title"]', 'Print new title');
    dom.window.document.querySelector('[data-protocol-print]').click();
    assert.equal(printed, false);
    await delay(80);
    assert.equal(printed, true);
  } finally { dom.window.close(); }
});
