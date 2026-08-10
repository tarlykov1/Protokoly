(() => {
  const request = async (path, options) => {
    const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
    if (!response.ok) throw new Error((await response.json()).detail || 'Не удалось выполнить действие');
    return response.json();
  };
  document.querySelector('#template-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    await request('/employee-lists', {method: 'POST', body: JSON.stringify({name: form.name.value, employee_ids: [...form.employee_ids.selectedOptions].map(item => +item.value)})});
    location.reload();
  });
  document.addEventListener('click', async event => {
    const card = event.target.closest('[data-template-id]');
    if (card && event.target.closest('.delete-template') && confirm('Удалить шаблон?')) {
      await request(`/employee-lists/${card.dataset.templateId}`, {method: 'DELETE'});
      card.remove();
    }
  });
})();
