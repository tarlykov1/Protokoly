(() => {
  const meta = document.querySelector('meta[name="protocol-version"]');
  if (!meta) return;
  const original = window.fetch.bind(window);
  let queue = Promise.resolve();
  let conflicted = false;
  window.fetch = (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const changesProtocol = /^\/(protocols\/\d+|protocol-tasks\/\d+)\//.test(url.pathname);
    if (url.origin !== location.origin || ['GET','HEAD','OPTIONS'].includes(method) || !changesProtocol || url.pathname.endsWith('/presence')) return original(input, init);
    const pending = queue.catch(() => {}).then(async () => {
      if (conflicted) throw new Error('Документ изменён. Сохраните свой текст и обновите страницу.');
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      headers.set('X-Protocol-Version', meta.content);
      let body = init.body;
      if (url.pathname.endsWith('/editor/save') && typeof body === 'string') {
        body = JSON.stringify({...JSON.parse(body), version: Number(meta.content)});
      }
      const response = await original(input, {...init, body, headers});
      if (response.ok) {
        const data = url.pathname.endsWith('/editor/save') ? await response.clone().json().catch(() => null) : null;
        meta.content = String(response.headers.get('X-Protocol-Version') || data?.version || Number(meta.content) + 1);
        if (window.protocolEditor) window.protocolEditor.version = Number(meta.content);
        const documentRoot = document.querySelector('.protocol-document[data-protocol-id]');
        if (documentRoot) documentRoot.dataset.version = meta.content;
        for (const field of document.querySelectorAll('input[name="protocol_version"]')) field.value = meta.content;
      } else if (response.status === 409) conflicted = true;
      return response;
    });
    queue = pending;
    return pending;
  };
  document.addEventListener('submit', event => {
    const form = event.target;
    if (form.method.toUpperCase() !== 'POST') return;
    let field = form.querySelector('input[name="protocol_version"]');
    if (!field) { field = document.createElement('input'); field.type = 'hidden'; field.name = 'protocol_version'; form.append(field); }
    field.value = meta.content;
  }, true);
})();
