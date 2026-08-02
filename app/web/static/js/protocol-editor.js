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
    sections: [...document.querySelectorAll('.section-row')].map(row => ({id: row.dataset.sectionId, title: value(row, '.section-title')})),
    tasks: rows().map(row => ({
      id: row.dataset.taskId, number: value(row, '.task-number'), title: value(row, '.task-title'),
      description: value(row, '.task-description'), employee_ids: [...row.querySelector('.task-employees').selectedOptions].map(o => +o.value),
      deadline: value(row, '.task-deadline'), section_id: value(row, '.task-section'), priority: value(row, '.task-priority'),
      task_mode: value(row, '.task-mode'), position: rows().indexOf(row), is_controlled: row.querySelector('.task-controlled').checked
    }))
  });
  const message = (text, error = false) => { const box = document.querySelector('#editor-message'); box.textContent = text; box.className = `alert ${error ? 'alert-danger' : 'alert-success'}`; };
  document.querySelector('#save-editor').addEventListener('click', async () => { try { await request(`/protocols/${id}/editor/save`, {method:'POST', body:JSON.stringify(serialize())}); message('Изменения сохранены'); } catch(e) { message(e.message, true); } });
  document.querySelector('#select-all').addEventListener('change', e => { rows().forEach(row => row.querySelector('.task-select').checked = e.target.checked); updateCount(); });
  document.addEventListener('change', e => { if (e.target.matches('.task-select')) updateCount(); });
  const updateCount = () => document.querySelector('#selected-count').textContent = document.querySelectorAll('.task-select:checked').length;
  document.querySelector('#bulk-apply').addEventListener('click', async () => {
    const task_ids = [...document.querySelectorAll('.task-select:checked')].map(input => +input.closest('tr').dataset.taskId);
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
  let dragged = null;
  document.addEventListener('dragstart', e => {
    dragged = e.target.closest('.task-row');
    if (dragged) { dragged.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; }
  });
  document.addEventListener('dragend', () => { if (dragged) dragged.classList.remove('dragging'); dragged = null; });
  document.addEventListener('dragover', e => { if (dragged && e.target.closest('.task-row, .section-row')) e.preventDefault(); });
  document.addEventListener('drop', e => {
    if (!dragged) return;
    const target = e.target.closest('.task-row, .section-row');
    if (!target || target === dragged) return;
    e.preventDefault();
    if (target.classList.contains('section-row')) {
      target.after(dragged);
      dragged.querySelector('.task-section').value = target.dataset.sectionId;
    } else {
      target.before(dragged);
      dragged.querySelector('.task-section').value = target.querySelector('.task-section').value;
    }
    message('Порядок изменён — сохраните редактор');
  });
  document.addEventListener('change', e => {
    if (!e.target.matches('.task-section')) return;
    const section = document.querySelector(`.section-row[data-section-id="${e.target.value}"]`);
    const row = e.target.closest('.task-row');
    const peers = rows().filter(item => item !== row && item.querySelector('.task-section').value === e.target.value);
    (peers.at(-1) || section).after(row);
  });
  let timer; document.querySelector('#employee-search').addEventListener('input', e => { clearTimeout(timer); timer = setTimeout(async () => { const result = await request(`/employees/search?q=${encodeURIComponent(e.target.value)}`); document.querySelector('#employee-results').innerHTML = result.map(item => `<div>${item.full_name}</div>`).join(''); }, 200); });
  document.addEventListener('focusin', e => { if (e.target.matches('.text-clamp')) e.target.classList.add('expanded'); });
  document.addEventListener('focusout', e => { if (e.target.matches('.text-clamp')) e.target.classList.remove('expanded'); });
})();
