(() => {
  const list = document.querySelector('#signatory-list');
  const addButton = document.querySelector('#add-signatory');
  if (!list || !addButton) return;

  const employeeOptions = [...document.querySelectorAll('.task-employees option')];
  const employees = [];
  const seen = new Set();
  employeeOptions.forEach(option => {
    if (!option.value || seen.has(option.value)) return;
    seen.add(option.value);
    employees.push({id: option.value, name: option.textContent.trim()});
  });
  employees.sort((a, b) => a.name.localeCompare(b.name, 'ru'));

  const panel = document.createElement('div');
  panel.className = 'signatory-template-panel border rounded p-3 mb-3 bg-light';
  panel.innerHTML = `
    <div class="fw-semibold mb-1">Шаблон руководителя / подписанта</div>
    <div class="small text-muted mb-3">Выберите тип подписанта и сотрудника. ФИО будет заполнено автоматически, должность при необходимости можно уточнить вручную.</div>
    <div class="row g-2 align-items-end">
      <label class="col-md-3">
        <span class="form-label">Роль</span>
        <select class="form-select" id="signatory-template-role">
          <option value="Руководитель">Руководитель</option>
          <option value="Председатель">Председатель</option>
          <option value="Подписант">Подписант</option>
          <option value="Секретарь">Секретарь</option>
        </select>
      </label>
      <label class="col-md-6">
        <span class="form-label">Сотрудник</span>
        <select class="form-select" id="signatory-template-employee">
          <option value="">Выберите сотрудника</option>
          ${employees.map(employee => `<option value="${employee.id}">${employee.name.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</option>`).join('')}
        </select>
      </label>
      <div class="col-md-3 d-grid"><button type="button" class="btn btn-outline-primary" id="apply-signatory-template">Добавить подписанта</button></div>
    </div>`;

  addButton.parentElement.insertBefore(panel, addButton);

  document.querySelector('#apply-signatory-template')?.addEventListener('click', () => {
    const employee = document.querySelector('#signatory-template-employee');
    const role = document.querySelector('#signatory-template-role');
    const selected = employee?.selectedOptions?.[0];
    if (!selected || !selected.value) {
      employee?.focus();
      return;
    }

    addButton.click();
    const row = list.querySelector('.signatory-row:last-child');
    if (!row) return;
    row.querySelector('.signatory-role').value = role.value;
    row.querySelector('.signatory-name').value = selected.textContent.trim();
    row.querySelector('.signatory-position').focus();
  });
})();
