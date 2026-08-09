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
    sections: [...document.querySelectorAll('.protocol-section[data-section-id]')].map((section, sort_order) => ({id:section.dataset.sectionId,title:section.querySelector('.section-title').value,sort_order})),
    tasks: rows().map(row => ({
      id: row.dataset.taskId, number: value(row, '.task-number'), title: value(row, '.task-title'),
      description: value(row, '.task-description'), employee_ids: [...row.querySelector('.task-employees').selectedOptions].map(o => +o.value),
      participant_group_ids: [...row.querySelector('.task-groups').selectedOptions].map(o => +o.value),
      deadline: value(row, '.task-deadline'), section_id: row.closest('.section-body')?.dataset.sectionId || value(row, '.task-section'), priority: value(row, '.task-priority'),
      task_mode: value(row, '.task-mode'), parent_task_id: value(row, '.task-parent') || null, position: rows().indexOf(row), is_controlled: row.querySelector('.task-controlled').checked
    }))
  });
  const message = (text, error = false) => { const box = document.querySelector('#editor-message'); box.textContent = text; box.className = `alert ${error ? 'alert-danger' : 'alert-success'}`; };
  const status = document.querySelector('#save-status');
  let saveTimer; let savePromise = Promise.resolve();
  const save = () => {
    clearTimeout(saveTimer); status.textContent = 'Сохранение…'; status.className = 'save-status is-saving';
    savePromise = request(`/protocols/${id}/editor/save`, {method:'POST', body:JSON.stringify(serialize())})
      .then(() => { rows().forEach(row => row.classList.remove('is-dirty')); status.textContent = 'Все изменения сохранены'; status.className = 'save-status is-saved'; })
      .catch(e => { status.textContent = 'Не удалось сохранить'; status.className = 'save-status is-error'; message(e.message, true); throw e; });
    return savePromise;
  };
  const scheduleSave = () => { clearTimeout(saveTimer); status.textContent = 'Есть несохранённые изменения'; status.className = 'save-status is-dirty'; saveTimer = setTimeout(save, 600); };
  document.querySelector('#save-editor').addEventListener('click', save);
  document.querySelector('#select-all').addEventListener('change', e => { rows().forEach(row => row.querySelector('.task-select').checked = e.target.checked); updateCount(); });
  document.addEventListener('change', e => { if (e.target.matches('.task-select')) updateCount(); });
  const updateCount = () => document.querySelector('#selected-count').textContent = document.querySelectorAll('.task-select:checked').length;
  document.querySelector('#bulk-apply').addEventListener('click', async () => {
    const task_ids = [...document.querySelectorAll('.task-select:checked')].map(input => +input.closest('.task-row').dataset.taskId);
    if (!task_ids.length) return message('Выберите поручения', true);
    const changes = {}; [['employee_id','#bulk-employee'],['deadline','#bulk-deadline'],['section_id','#bulk-section'],['task_mode','#bulk-mode']].forEach(([key, selector]) => { const val = document.querySelector(selector).value; if (val) changes[key] = val; });
    await request(`/protocols/${id}/editor/bulk`, {method:'POST', body:JSON.stringify({task_ids, changes})}); location.reload();
  });
  document.querySelector('#add-task').addEventListener('click', async () => { clearTimeout(saveTimer); await save(); await request(`/protocols/${id}/editor/tasks`, {method:'POST', body:'{}'}); location.reload(); });
  document.querySelector('#add-section').addEventListener('click', async () => { const title = prompt('Название раздела'); if (title) { await request(`/protocols/${id}/editor/sections`, {method:'POST', body:JSON.stringify({title})}); location.reload(); } });
  document.querySelector('#add-participant-group')?.addEventListener('click', async () => { const name=prompt('Название списка'); if(name){await request(`/protocols/${id}/participant-groups`,{method:'POST',body:JSON.stringify({name})});location.reload();} });
  document.querySelector('#participant-template')?.addEventListener('change', async e => { if(e.target.value){await request(`/protocols/${id}/participant-groups/from-template/${e.target.value}`,{method:'POST'});location.reload();} });
  document.querySelectorAll('.participant-card').forEach(card => card.addEventListener('click', async e => { const gid=card.dataset.groupId;
    if(e.target.closest('.delete-participant-group')&&confirm('Удалить список?')){await request(`/protocols/${id}/participant-groups/${gid}`,{method:'DELETE'});location.reload();}
    if(e.target.closest('.save-participant-template')){const name=prompt('Название сохранённого списка');if(name){await request(`/protocols/${id}/participant-groups/${gid}/save-template`,{method:'POST',body:JSON.stringify({name})});location.reload();}}
    if(e.target.closest('.copy-attendees')){await request(`/protocols/${id}/participant-groups/${gid}/copy-attendees`,{method:'POST'});location.reload();}
    if(e.target.closest('.edit-participant-group')){const raw=prompt('ID сотрудников через запятую');if(raw!==null){await request(`/protocols/${id}/participant-groups/${gid}`,{method:'PUT',body:JSON.stringify({employee_ids:raw.split(',').map(v=>v.trim()).filter(Boolean)})});location.reload();}}
  }));
  document.addEventListener('click', async e => {
    const section = e.target.closest('.protocol-section[data-section-id]');
    if (section && e.target.closest('.delete-section') && confirm('Удалить раздел? Поручения останутся без раздела.')) { await request(`/protocols/${id}/editor/sections/${section.dataset.sectionId}`, {method:'DELETE'}); location.reload(); return; }
    const row = e.target.closest('.task-row'); if (!row) return;
    if (e.target.closest('.delete-task') && confirm('Удалить поручение?')) { await request(`/protocols/${id}/editor/tasks/${row.dataset.taskId}`, {method:'DELETE'}); row.remove(); }
    if (e.target.closest('.duplicate-task')) { await request(`/protocols/${id}/editor/tasks/${row.dataset.taskId}/duplicate`, {method:'POST'}); location.reload(); }
    if (e.target.closest('.memo-assignee')) { const employee_id = row.querySelector('.task-employees').value; if (!employee_id) return message('Сначала выберите сотрудника из справочника', true); await request(`/protocols/${id}/editor/tasks/${row.dataset.taskId}/match-assignee`, {method:'POST', body:JSON.stringify({source_name:e.target.dataset.sourceName, employee_id})}); location.reload(); }
  });
  const renumber = () => rows().forEach((row, index) => { row.querySelector('.task-number').value = String(index + 1); row.classList.add('is-dirty'); });
  const markDirty = target => target.closest('.task-row')?.classList.add('is-dirty');
  document.addEventListener('input', e => { if (e.target.closest('.task-row')) markDirty(e.target); if (e.target.matches('.task-row input,.task-row textarea,.section-title')) scheduleSave(); if (e.target.matches('.parent-task-search')) { const query=e.target.value.toLowerCase(); [...e.target.closest('.parent-task-field').querySelector('.task-parent').options].forEach((option,index) => { if(index) option.hidden=!option.text.toLowerCase().includes(query); }); } });
  document.addEventListener('change', e => { if (e.target.matches('.task-row select,.task-row input')) scheduleSave(); if (e.target.matches('.task-mode')) e.target.closest('.task-content').querySelector('.parent-task-field').classList.toggle('d-none', e.target.value !== 'subtasks'); });
  const syncSectionSelects = () => {
    document.querySelectorAll('.section-body').forEach(body => {
      body.querySelectorAll('.task-section').forEach(select => { select.value = body.dataset.sectionId; });
    });
  };
  if (window.Sortable) {
    document.querySelectorAll('.section-body').forEach(body => {
      new Sortable(body, {
        group: 'protocol-tasks', handle: '.drag-handle', draggable: '.task-row', animation: 150,
        ghostClass: 'sortable-ghost', chosenClass: 'sortable-chosen', dragClass: 'dragging', onStart: () => body.classList.add('drop-active'), onEnd: () => { document.querySelectorAll('.section-body').forEach(item => item.classList.remove('drop-active')); syncSectionSelects(); renumber(); scheduleSave(); }
      });
    });
    new Sortable(document.querySelector('.editor-sections'), {handle:'.section-handle', draggable:'.protocol-section[data-section-id]', animation:150, onEnd:scheduleSave});
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
  let timer; document.querySelector('#employee-search')?.addEventListener('input', e => { clearTimeout(timer); timer = setTimeout(async () => { const result = await request(`/employees/search?q=${encodeURIComponent(e.target.value)}`); document.querySelector('#employee-results').innerHTML = result.map(item => `<div>${item.full_name}</div>`).join(''); }, 200); });
  document.addEventListener('focusin', e => { if (e.target.matches('.text-clamp')) e.target.classList.add('expanded'); });
  document.addEventListener('focusout', e => { if (e.target.matches('.text-clamp')) e.target.classList.remove('expanded'); });
})();
