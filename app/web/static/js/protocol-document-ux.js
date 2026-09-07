(() => {
  const editor = document.querySelector('.editor-sections');

  const editorRows = () => [...document.querySelectorAll('.task-row')];

  const renumberEditorTasks = () => {
    const rows = editorRows();
    if (!rows.length) return;

    const byId = new Map(rows.map(row => [String(row.dataset.taskId), row]));
    const isChild = row => {
      const mode = row.querySelector('.task-mode')?.value;
      const parentId = row.querySelector('.task-parent')?.value;
      return mode === 'subtasks' && parentId && byId.has(String(parentId)) && String(parentId) !== String(row.dataset.taskId);
    };

    const roots = rows.filter(row => !isChild(row));
    const rootNumbers = new Map(roots.map((row, index) => [String(row.dataset.taskId), String(index + 1)]));
    const cache = new Map();

    const resolveNumber = (row, chain = new Set()) => {
      const id = String(row.dataset.taskId);
      if (cache.has(id)) return cache.get(id);
      if (chain.has(id)) return rootNumbers.get(id) || String(rows.indexOf(row) + 1);

      const nextChain = new Set(chain);
      nextChain.add(id);
      let number = rootNumbers.get(id);

      if (isChild(row)) {
        const parentId = String(row.querySelector('.task-parent').value);
        const parent = byId.get(parentId);
        const siblings = rows.filter(candidate => isChild(candidate) && String(candidate.querySelector('.task-parent').value) === parentId);
        const childIndex = siblings.indexOf(row) + 1;
        number = `${resolveNumber(parent, nextChain)}.${childIndex}`;
      }

      number = number || String(rows.indexOf(row) + 1);
      cache.set(id, number);
      return number;
    };

    rows.forEach(row => {
      const input = row.querySelector('.task-number');
      if (!input) return;
      const number = resolveNumber(row);
      if (input.value === number) return;
      input.value = number;
      row.classList.add('is-dirty');
      input.dispatchEvent(new Event('input', {bubbles: true}));
    });
  };

  if (editor) {
    let renumberTimer;
    const queueRenumber = () => {
      clearTimeout(renumberTimer);
      renumberTimer = setTimeout(renumberEditorTasks, 0);
    };

    document.addEventListener('change', event => {
      if (event.target.matches('.task-mode,.task-parent,.task-section')) queueRenumber();
    });

    const observer = new MutationObserver(mutations => {
      if (mutations.some(mutation => mutation.type === 'childList' && ([...mutation.addedNodes, ...mutation.removedNodes].some(node => node.nodeType === 1 && (node.matches?.('.task-row') || node.querySelector?.('.task-row')))))) {
        queueRenumber();
      }
    });
    observer.observe(editor, {childList: true, subtree: true});
    queueRenumber();
  }

  const match = window.location.pathname.match(/^\/protocols\/(\d+)\/?$/);
  const protocolId = match?.[1];
  if (!protocolId) return;

  const saveInlineText = async (element, original) => {
    const task = element.closest('.document-task');
    if (!task) return;
    const field = element.dataset.inlineField;
    const value = element.textContent.trim();
    element.contentEditable = 'false';
    element.classList.remove('inline-editing');
    if (value === original.trim()) return;

    element.classList.add('inline-saving');
    try {
      const response = await fetch(`/protocols/${protocolId}/editor/save`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({tasks: [{id: Number(task.dataset.taskId), [field]: value}]})
      });
      if (!response.ok) throw new Error();
      element.classList.remove('inline-saving');
      element.classList.add('inline-saved');
      setTimeout(() => element.classList.remove('inline-saved'), 900);
    } catch (_) {
      element.textContent = original;
      element.classList.remove('inline-saving');
      element.classList.add('inline-save-error');
      setTimeout(() => element.classList.remove('inline-save-error'), 1500);
    }
  };

  document.querySelectorAll('[data-inline-field]').forEach(element => {
    element.title = 'Дважды щёлкните, чтобы быстро исправить текст';
    element.addEventListener('dblclick', () => {
      if (element.isContentEditable) return;
      const original = element.textContent;
      element.dataset.originalText = original;
      element.contentEditable = 'true';
      element.classList.add('inline-editing');
      element.focus();
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(element);
      selection.removeAllRanges();
      selection.addRange(range);
    });
    element.addEventListener('keydown', event => {
      if (!element.isContentEditable) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        element.textContent = element.dataset.originalText || element.textContent;
        element.contentEditable = 'false';
        element.classList.remove('inline-editing');
      }
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey || element.dataset.inlineField === 'title')) {
        event.preventDefault();
        element.blur();
      }
    });
    element.addEventListener('blur', () => {
      if (!element.isContentEditable) return;
      saveInlineText(element, element.dataset.originalText || '');
    });
  });
})();
