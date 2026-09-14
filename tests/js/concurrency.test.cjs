const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');

test('mixed protocol writes share a queue and advance editor versions', async () => {
  const dom = new JSDOM('<meta name="protocol-version" content="1"><div class="protocol-document" data-protocol-id="1" data-version="1"></div>', {url:'http://localhost', runScripts:'outside-only'});
  const w = dom.window;
  w.Headers = Headers; w.Request = Request; w.Response = Response;
  w.protocolEditor = {version:1};
  let active = 0, maxActive = 0;
  const sent = [];
  w.fetch = async (url, init) => {
    active++; maxActive = Math.max(active, maxActive);
    sent.push([url, init.headers.get('X-Protocol-Version'), init.body]);
    await new Promise(resolve => setTimeout(resolve, 5));
    active--;
    const version = Number(init.headers.get('X-Protocol-Version')) + 1;
    return new Response(JSON.stringify({version}), {headers:{'Content-Type':'application/json','X-Protocol-Version':String(version)}});
  };
  w.eval(fs.readFileSync('app/web/static/js/concurrency.js','utf8'));
  await Promise.all([
    w.fetch('/protocols/1/editor/sections', {method:'POST',body:'{}'}),
    w.fetch('/protocols/1/editor/save', {method:'POST',body:JSON.stringify({version:1,protocol:{title:'new'}})})
  ]);
  assert.equal(maxActive, 1);
  assert.deepEqual(sent.map(item=>item[1]), ['1','2']);
  assert.equal(JSON.parse(sent[1][2]).version, 2);
  assert.equal(w.protocolEditor.version, 3);
  assert.equal(w.document.querySelector('.protocol-document').dataset.version, '3');
  dom.window.close();
});
