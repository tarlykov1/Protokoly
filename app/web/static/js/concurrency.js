(() => {
  const meta = document.querySelector('meta[name="protocol-version"]');
  if (!meta) return;
  const original = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (url.origin !== location.origin || ['GET','HEAD','OPTIONS'].includes(method)) return original(input, init);
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
    headers.set('X-Protocol-Version', meta.content);
    const response = await original(input, {...init, headers});
    if (response.ok) {
      // Full form submissions navigate; asynchronous document edits return their version.
      const body = await response.clone().json().catch(() => null);
      if (body && body.version) meta.content = String(body.version);
      else meta.content = String(Number(meta.content) + 1);
      for (const field of document.querySelectorAll('input[name="protocol_version"]')) field.value = meta.content;
    }
    return response;
  };
  document.addEventListener('submit', event => {
    const form = event.target;
    if (form.method.toUpperCase() !== 'POST') return;
    let field = form.querySelector('input[name="protocol_version"]');
    if (!field) { field = document.createElement('input'); field.type = 'hidden'; field.name = 'protocol_version'; form.append(field); }
    field.value = meta.content;
  }, true);
})();
