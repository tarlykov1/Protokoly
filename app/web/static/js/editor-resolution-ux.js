(() => {
  const statusLabels = {
    pending: 'Ожидает выполнения',
    in_progress: 'В работе',
    completed: 'Выполнено',
    overdue: 'Просрочено',
    rejected: 'Возвращено на доработку'
  };

  const localizeControlPage = () => {
    document.querySelectorAll('select[name="status"] option').forEach(option => {
      const value = option.value || option.textContent.trim();
      if (statusLabels[value]) option.textContent = statusLabels[value];
    });
    document.querySelectorAll('/html/body')
    document.querySelectorAll('.protocol-validation code').forEach(code => code.remove());
    document.querySelectorAll('td').forEach(cell => {
      const text = cell.textContent.trim();
      if (statusLabels[text]) cell.textContent = statusLabels[text];
    });
  };

  const request = async (path, options = {}) => {
    const response = await fetch(path, {
      headers: {'Content-Type': 'application/json'},
      ...options
    });
    if (!response.ok) {
      let detail = 'Не удалось выполнить действие';
      try {
        const body = await response.json();
        detail = body.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return response.json();
  };

  const ensureModal = () => {
    let modal = document.querySelector('#assignee-resolution-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.className = 'modal fade';
    modal.id = 'assignee-resolution-modal';
    modal.tabIndex = -1;
    modal.innerHTML = `
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <div>
              <h2 class="modal-title h5">Уточнить исполнителя</h2>
              <div class="small text-muted" id="assignee-resolution-source"></div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Закрыть"></button>
          </div>
          <div class="modal-body">
            <div id="assignee-resolution-message" class="alert d-none"></div>
            <div id="assignee-select-pane">
              <label class="form-label" for="assignee-resolution-search">Найдите сотрудника в справочнике</label>
              <input id="assignee-resolution-search" class="form-control mb-3" type="search" placeholder="ФИО, должность или подразделение">
              <div id="assignee-resolution-list" class="list-group" style="max-height:360px;overflow:auto"></div>
            </div>
            <div id="assignee-create-pane" class="d-none">
              <p class="mb-3">Если сотрудника ещё нет в справочнике, создайте его здесь. После создания он сразу будет назначен исполнителем этого поручения.</p>
              <label class="form-label" for="assignee-new-name">ФИО</label>
              <input id="assignee-new-name" class="form-control" autocomplete="off">
            </div>
          </div>
          <div class="modal-footer justify-content-between">
            <button type="button" id="assignee-toggle-create" class="btn btn-outline-primary">Создать нового сотрудника</button>
            <div class="d-flex gap-2">
              <button type="button" class="btn btn-light" data-bs-dismiss="modal">Отмена</button>
              <button type="button" id="assignee-create-confirm" class="btn btn-primary d-none">Создать и назначить</button>
            </div>
          </div>
        </div>
      </div>`;
    document.body.append(modal);
    return modal;
  };

  let current = null;

  const showError = text => {
    const box = document.querySelector('#assignee-resolution-message');
    box.textContent = text;
    box.className = 'alert alert-danger';
  };

  const openAssigneeModal = (button, createMode = false) => {
    const row = button.closest('.task-row');
    const sourceName = button.dataset.sourceName || '';
    const select = row?.querySelector('.task-employees');
    if (!row || !select) return;
    current = {row, sourceName, taskId: row.dataset.taskId, select};
    const modal = ensureModal();
    modal.querySelector('#assignee-resolution-source').textContent = `В документе указано: ${sourceName}`;
    modal.querySelector('#assignee-resolution-message').className = 'alert d-none';
    modal.querySelector('#assignee-new-name').value = sourceName;
    const list = modal.querySelector('#assignee-resolution-list');
    list.innerHTML = '';
    [...select.options].forEach(option => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'list-group-item list-group-item-action text-start';
      item.dataset.employeeId = option.value;
      item.dataset.search = option.textContent.toLowerCase();
      item.innerHTML = `<strong>${option.textContent}</strong>`;
      item.addEventListener('click', async () => {
        try {
          item.disabled = true;
          await request(`/protocols/${window.protocolEditor.protocolId}/editor/tasks/${current.taskId}/match-assignee`, {
            method: 'POST',
            body: JSON.stringify({source_name: current.sourceName, employee_id: Number(option.value)})
          });
          location.reload();
        } catch (error) {
          item.disabled = false;
          showError(error.message);
        }
      });
      list.append(item);
    });
    modal.querySelector('#assignee-resolution-search').value = '';
    const selectPane = modal.querySelector('#assignee-select-pane');
    const createPane = modal.querySelector('#assignee-create-pane');
    const createConfirm = modal.querySelector('#assignee-create-confirm');
    const toggle = modal.querySelector('#assignee-toggle-create');
    const setMode = creating => {
      selectPane.classList.toggle('d-none', creating);
      createPane.classList.toggle('d-none', !creating);
      createConfirm.classList.toggle('d-none', !creating);
      toggle.textContent = creating ? 'Выбрать из справочника' : 'Создать нового сотрудника';
    };
    setMode(createMode);
    bootstrap.Modal.getOrCreateInstance(modal).show();
  };

  document.addEventListener('input', event => {
    if (event.target.id !== 'assignee-resolution-search') return;
    const query = event.target.value.trim().toLowerCase();
    document.querySelectorAll('#assignee-resolution-list [data-search]').forEach(item => {
      item.classList.toggle('d-none', query && !item.dataset.search.includes(query));
    });
  });

  document.addEventListener('click', event => {
    const choose = event.target.closest('.memo-assignee');
    const create = event.target.closest('.create-memo-assignee');
    if (!choose && !create) return;
    event.preventDefault();
    event.stopPropagation();
    openAssigneeModal(choose || create, Boolean(create));
  }, true);

  document.addEventListener('click', event => {
    if (event.target.id === 'assignee-toggle-create') {
      const modal = ensureModal();
      const creating = modal.querySelector('#assignee-create-pane').classList.contains('d-none');
      modal.querySelector('#assignee-select-pane').classList.toggle('d-none', creating);
      modal.querySelector('#assignee-create-pane').classList.toggle('d-none', !creating);
      modal.querySelector('#assignee-create-confirm').classList.toggle('d-none', !creating);
      event.target.textContent = creating ? 'Выбрать из справочника' : 'Создать нового сотрудника';
    }
    if (event.target.id === 'assignee-create-confirm' && current) {
      const input = document.querySelector('#assignee-new-name');
      const fullName = input.value.trim();
      if (!fullName) return showError('Укажите ФИО сотрудника');
      event.target.disabled = true;
      request(`/protocols/${window.protocolEditor.protocolId}/editor/tasks/${current.taskId}/create-assignee`, {
        method: 'POST',
        body: JSON.stringify({source_name: current.sourceName, full_name: fullName})
      }).then(() => location.reload()).catch(error => {
        event.target.disabled = false;
        showError(error.message);
      });
    }
  });

  localizeControlPage();
})();
