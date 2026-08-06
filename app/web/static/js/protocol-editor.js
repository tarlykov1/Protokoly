(() => {
  const id = window.protocolEditor.protocolId;
  const rows = () => [...document.querySelectorAll('.task-row')];
  const request = async (path, options = {}) => {
    const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
    if (!response.ok) throw new Error('Не удалось выполнить действие');
    return response.json();
  };
  const value = (row, selector) => row.querySelector(selector).value;
  const serialize = () => ({
    sections: [...document.querySelectorAll('.protocol-section')].map(section => { const body=section.querySelector('.section-body'); const title=section.querySelector('.section-title'); return title ? {id:body.dataset.sectionId,title:title.value} : null; }).filter(Boolean),
    tasks: rows().map(row => ({
      id: row.dataset.taskId, number: value(row, '.task-number'), title: value(row, '.task-title'),
      description: value(row, '.task-description'), employee_ids: [...row.querySelector('.task-employees').selectedOptions].map(o => +o.value),
      deadline: value(row, '.task-deadline'), section_id: row.closest('.section-body')?.dataset.sectionId || value(row, '.task-section'), priority: value(row, '.task-priority'),
      task_mode: value(row, '.task-mode'), position: rows().indexOf(row), is_controlled: row.querySelector('.task-controlled').checked
    }))
  });
  const message = (text, error = false) => { const box = document.querySelector('#editor-message'); box.textContent = text; box.className = `alert ${error ? 'alert-danger' : 'alert-success'}`; };
  document.querySelector('#save-editor').addEventListener('click', async () => { try { await request(`/protocols/${id}/editor/save`, {method:'POST', body:JSON.stringify(serialize())}); message('Изменения сохранены'); } catch(e) { message(e.message, true); } });
  document.querySelector('#select-all').addEventListener('change', e => { rows().forEach(row => row.querySelector('.task-select').checked = e.target.checked); updateCount(); });
  document.addEventListener('change', e => { if (e.target.matches('.task-select')) updateCount(); });
  const updateCount = () => document.querySelector('#selected-count').textContent = document.querySelectorAll('.task-select:checked').length;
  document.querySelector('#bulk-apply').addEventListener('click', async () => {
    const task_ids = [...document.querySelectorAll('.task-select:checked')].map(input => +input.closest('.task-row').dataset.taskId);
    if (!task_ids.length) return message('Выберите поручения', true);
    const changes = {}; [['employee_id','#bulk-employee'],['deadline','#bulk-deadline'],['section_id','#bulk-section'],['task_mode','#bulk-mode']].forEach(([key, selector]) => { const val = document.querySelector(selector).value; if (val) changes[key] = val; });
    await request(`/protocols/${id}/editor/bulk`, {method:'POST', body:JSON.stringify({task_ids, changes})}); location.reload();
  });
  document.querySelector('#add-task').addEventListener('click', async () => { await request(`/protocols/${id}/editor/tasks`, {method:'POST', body:'{}'}); location.reload(); });
  document.querySelector('#add-section').addEventListener('click', async () => { const title = prompt('Название раздела'); if (title) { await request(`/protocols/${id}/editor/sections`, {method:'POST', body:JSON.stringify({title})}); location.reload(); } });
  document.addEventListener('click', async e => {
    const row = e.target.closest('.task-row'); if (!row) return;
    if (e.target.closest('.delete-task') && confirm('Удалить поручение?')) { await request(`/protocols/${id}/editor/tasks/${row.dataset.taskId}`, {method:'DELETE'}); row.remove(); }
    if (e.target.closest('.duplicate-task')) { await request(`/protocols/${id}/editor/tasks/${row.dataset.taskId}/duplicate`, {method:'POST'}); location.reload(); }
    if (e.target.closest('.memo-assignee')) { const employee_id = row.querySelector('.task-employees').value; if (!employee_id) return message('Сначала выберите сотрудника из справочника', true); await request(`/protocols/${id}/editor/tasks/${row.dataset.taskId}/match-assignee`, {method:'POST', body:JSON.stringify({source_name:e.target.dataset.sourceName, employee_id})}); location.reload(); }
  });
  const renumber = () => rows().forEach((row, index) => { row.querySelector('.task-number').value = String(index + 1); row.classList.add('is-dirty'); });
  const markDirty = target => target.closest('.task-row')?.classList.add('is-dirty');
  document.addEventListener('input', e => { if (e.target.closest('.task-row')) markDirty(e.target); });
  const syncSectionSelects = () => {
    document.querySelectorAll('.section-body').forEach(body => {
      body.querySelectorAll('.task-section').forEach(select => { select.value = body.dataset.sectionId; });
    });
  };
  if (window.Sortable) {
    document.querySelectorAll('.section-body').forEach(body => {
      new Sortable(body, {
        group: 'protocol-tasks', handle: '.drag-handle', draggable: '.task-row', animation: 150,
        ghostClass: 'sortable-ghost', chosenClass: 'sortable-chosen', dragClass: 'dragging', onStart: () => body.classList.add('drop-active'), onEnd: () => { document.querySelectorAll('.section-body').forEach(item => item.classList.remove('drop-active')); syncSectionSelects(); renumber(); message('Порядок изменён — сохраните редактор'); }
      });
    });
  } else {
    let dragged = null;
    document.addEventListener('dragstart', e => {
      dragged = e.target.closest('.task-row');
      if (dragged) { dragged.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; }
    });
    document.addEventListener('dragend', () => { if (dragged) dragged.classList.remove('dragging'); dragged = null; });
    document.addEventListener('dragover', e => { if (dragged && e.target.closest('.task-row, .section-row')) e.preventDefault(); });
    document.addEventListener('drop', e => {
      if (!dragged) return;
      const target = e.target.closest('.task-row, .section-body');
      if (!target || target === dragged) return;
      e.preventDefault();
      if (target.classList.contains('section-body')) {
        target.append(dragged);
        dragged.querySelector('.task-section').value = target.dataset.sectionId;
      } else {
        target.before(dragged);
        dragged.querySelector('.task-section').value = target.querySelector('.task-section').value;
      }
      syncSectionSelects();
      message('Порядок изменён — сохраните редактор');
    });
  }
  document.addEventListener('change', e => {
    if (!e.target.matches('.task-section')) return;
    const body = document.querySelector(`.section-body[data-section-id="${e.target.value}"]`);
    const row = e.target.closest('.task-row');
    body?.append(row);
    syncSectionSelects();
  });
  let timer; document.querySelector('#employee-search').addEventListener('input', e => { clearTimeout(timer); timer = setTimeout(async () => { const result = await request(`/employees/search?q=${encodeURIComponent(e.target.value)}`); document.querySelector('#employee-results').innerHTML = result.map(item => `<div>${item.full_name}</div>`).join(''); }, 200); });
  document.addEventListener('focusin', e => { if (e.target.matches('.text-clamp')) e.target.classList.add('expanded'); });
  document.addEventListener('focusout', e => { if (e.target.matches('.text-clamp')) e.target.classList.remove('expanded'); });
})();
