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

  document.addEventListener('protocol:renumber', renumberEditorTasks);

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

  let saveQueue = Promise.resolve();
  let saveFailed = false;
  const requestSave = async payload => {
    const response = await fetch(`/protocols/${protocolId}/editor/save`, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'Accept': 'application/json'}, body: JSON.stringify({...payload, version: Number(documentRoot.dataset.version)})
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Не удалось сохранить изменение');
    }
    const result = await response.json();
    documentRoot.dataset.version = result.version;
    return result;
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
    if (element.dataset.editing === '1' || element.classList.contains('inline-saving')) return;
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
      if (!control.checkValidity()) { control.reportValidity(); control.focus(); control.addEventListener('blur', commit, {once: true}); return; }
      const value = control.value.trim();
      if (value === (element.dataset.pendingValue ?? originalText)) { cancel(); return; }
      element.classList.add('inline-saving');
      const performSave = async () => {
      try {
        if (saveFailed) throw new Error('Предыдущее сохранение не выполнено. Скопируйте изменения и обновите страницу.');
        if (element.dataset.protocolField) {
          await requestSave({protocol: {[element.dataset.protocolField]: value}});
        } else if (element.dataset.inlineField) {
          const task = element.closest('.document-task');
          await requestSave({tasks: [{id: Number(task.dataset.taskId), [element.dataset.inlineField]: value}]});
        } else if (element.dataset.signatoryField) {
          const row = element.closest('.document-signatory');
          await requestSave({signatory_updates: [{id: Number(row.dataset.signatoryId), [element.dataset.signatoryField]: value}]});
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
        saveFailed = true;
        element.textContent = value || '—'; element.classList.remove('inline-editing'); delete element.dataset.editing; flash(element, false);
        window.alert(error.message);
      }
      };
      saveQueue = saveQueue.then(performSave);
      await saveQueue;
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

  const finishEditing = async () => {
    documentRoot.querySelectorAll('.inline-document-control').forEach(control => control.blur());
    await saveQueue;
    if (saveFailed || documentRoot.querySelector('.inline-document-control')) {
      window.alert('Сначала сохраните изменения документа.');
      return false;
    }
    return true;
  };
  document.querySelector('[data-protocol-print]')?.addEventListener('click', async () => {
    if (await finishEditing()) window.print();
  });
  document.querySelector('[data-protocol-pdf]')?.addEventListener('click', async () => {
    if (await finishEditing()) window.print();
  });
  document.querySelectorAll('a[href*="/export/docx"]').forEach(link => link.addEventListener('click', async event => {
    event.preventDefault();
    if (await finishEditing()) window.location.assign(link.href);
  }));
  window.addEventListener('beforeunload', event => {
    if (saveFailed || documentRoot.querySelector('.inline-saving,.inline-document-control')) {
      event.preventDefault(); event.returnValue = '';
    }
  });
})();
