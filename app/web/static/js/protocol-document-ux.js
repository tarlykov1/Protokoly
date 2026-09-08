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
      const nextChain = new Set(chain); nextChain.add(id);
      let number = rootNumbers.get(id);
      if (isChild(row)) {
        const parentId = String(row.querySelector('.task-parent').value);
        const parent = byId.get(parentId);
        const siblings = rows.filter(candidate => isChild(candidate) && String(candidate.querySelector('.task-parent').value) === parentId);
        number = `${resolveNumber(parent, nextChain)}.${siblings.indexOf(row) + 1}`;
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
    const queueRenumber = () => { clearTimeout(renumberTimer); renumberTimer = setTimeout(renumberEditorTasks, 0); };
    document.addEventListener('change', event => { if (event.target.matches('.task-mode,.task-parent,.task-section')) queueRenumber(); });
    const observer = new MutationObserver(mutations => {
      if (mutations.some(mutation => mutation.type === 'childList' && ([...mutation.addedNodes, ...mutation.removedNodes].some(node => node.nodeType === 1 && (node.matches?.('.task-row') || node.querySelector?.('.task-row')))))) queueRenumber();
    });
    observer.observe(editor, {childList: true, subtree: true});
    queueRenumber();
  }

  const documentRoot = document.querySelector('.protocol-document[data-protocol-id]');
  if (!documentRoot) return;
  const protocolId = documentRoot.dataset.protocolId;

  const normalizeDisplayedValue = element => {
    const value = element.textContent.trim();
    return ['—', 'Организация не указана', 'Название мероприятия не указано', 'Дата не указана', 'Время не указано', 'ФИО не указано', 'Должность не указана'].includes(value) ? '' : value;
  };

  const requestSave = async payload => {
    const response = await fetch(`/protocols/${protocolId}/editor/save`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Не удалось сохранить изменение');
    }
    return response.json();
  };

  const flash = (element, ok) => {
    element.classList.remove('inline-saving');
    element.classList.add(ok ? 'inline-saved' : 'inline-save-error');
    setTimeout(() => element.classList.remove(ok ? 'inline-saved' : 'inline-save-error'), 1200);
  };

  const editorFor = element => {
    const kind = element.dataset.editKind || 'text';
    const current = normalizeDisplayedValue(element);
    let control;
    if (kind === 'select') {
      control = document.createElement('select');
      control.className = 'form-select form-select-sm inline-document-control';
      (element.dataset.options || '').split('|').filter(Boolean).forEach(pair => {
        const [value, label] = pair.split(':');
        const option = document.createElement('option'); option.value = value; option.textContent = label;
        if (label === current || value === current) option.selected = true;
        control.append(option);
      });
    } else if (kind === 'textarea') {
      control = document.createElement('textarea'); control.rows = 3; control.className = 'form-control inline-document-control'; control.value = current;
    } else {
      control = document.createElement('input'); control.type = kind === 'date' || kind === 'time' ? kind : 'text'; control.className = 'form-control form-control-sm inline-document-control';
      control.value = current;
    }
    return control;
  };

  const beginEdit = element => {
    if (element.dataset.editing === '1') return;
    element.dataset.editing = '1';
    const originalHtml = element.innerHTML;
    const originalText = normalizeDisplayedValue(element);
    const control = editorFor(element);
    element.innerHTML = ''; element.append(control); element.classList.add('inline-editing');
    control.focus(); if (control.select) control.select();

    let cancelled = false;
    const cancel = () => { cancelled = true; element.innerHTML = originalHtml; element.classList.remove('inline-editing'); delete element.dataset.editing; };
    const commit = async () => {
      if (cancelled) return;
      const value = control.value.trim();
      element.classList.add('inline-saving');
      try {
        if (element.dataset.protocolField) {
          await requestSave({protocol: {[element.dataset.protocolField]: value}});
        } else if (element.dataset.inlineField) {
          const task = element.closest('.document-task');
          await requestSave({tasks: [{id: Number(task.dataset.taskId), [element.dataset.inlineField]: value}]});
        } else if (element.dataset.signatoryField) {
          const rows = [...document.querySelectorAll('.document-signatory')];
          const signatories = rows.map(row => ({
            role: row.querySelector('[data-signatory-field="role"]')?.dataset.pendingValue ?? normalizeDisplayedValue(row.querySelector('[data-signatory-field="role"]')),
            name_snapshot: row.querySelector('[data-signatory-field="name_snapshot"]')?.dataset.pendingValue ?? normalizeDisplayedValue(row.querySelector('[data-signatory-field="name_snapshot"]')),
            position_snapshot: row.querySelector('[data-signatory-field="position_snapshot"]')?.dataset.pendingValue ?? normalizeDisplayedValue(row.querySelector('[data-signatory-field="position_snapshot"]')),
            sort_order: Number(row.dataset.signatoryIndex || 0)
          }));
          const row = element.closest('.document-signatory');
          const index = Number(row.dataset.signatoryIndex || 0);
          signatories[index][element.dataset.signatoryField] = value;
          await requestSave({signatories});
        }
        const kind = element.dataset.editKind;
        if (kind === 'select') {
          element.textContent = control.selectedOptions[0]?.textContent || '—';
        } else {
          element.textContent = value || '—';
        }
        element.dataset.pendingValue = value;
        element.classList.remove('inline-editing'); delete element.dataset.editing; flash(element, true);
      } catch (error) {
        element.innerHTML = originalHtml; element.classList.remove('inline-editing'); delete element.dataset.editing; flash(element, false);
        window.alert(error.message);
      }
    };
    control.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); cancel(); }
      if (event.key === 'Enter' && control.tagName !== 'TEXTAREA') { event.preventDefault(); control.blur(); }
      if (event.key === 'Enter' && control.tagName === 'TEXTAREA' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); control.blur(); }
    });
    control.addEventListener('blur', commit, {once: true});
    if (control.tagName === 'SELECT') control.addEventListener('change', () => control.blur(), {once: true});
  };

  const editableSelector = '[data-protocol-field],[data-inline-field],[data-signatory-field]';
  document.querySelectorAll(editableSelector).forEach(element => {
    element.classList.add('inline-editable');
    element.title = 'Дважды щёлкните, чтобы изменить';
    element.addEventListener('dblclick', event => { event.preventDefault(); beginEdit(element); });
  });

  document.querySelector('[data-protocol-print]')?.addEventListener('click', () => window.print());
  document.querySelector('[data-protocol-pdf]')?.addEventListener('click', () => {
    document.body.classList.add('pdf-print-mode');
    window.print();
    setTimeout(() => document.body.classList.remove('pdf-print-mode'), 500);
  });
})();
