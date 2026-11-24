'use strict';
(() => {
  const el = id => document.getElementById(id);
  const text = (id, value) => { el(id).textContent = String(value ?? '—'); };
  const labels = {
    1: 'Новая', 2: 'Ждёт выполнения', 3: 'Выполняется',
    4: 'Ожидает контроля', 5: 'Завершена', 6: 'Отложена', 7: 'Прочий статус'
  };
  function showStatus(message, isError = false) {
    text('message', message);
    el('message').classList.toggle('error', isError);
  }
  function render(payload) {
    const when = new Date(payload.collected_at_utc);
    text('asof', Number.isNaN(when.getTime()) ? 'Дата снимка неизвестна' :
      `Снимок: ${new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Moscow' }).format(when)} МСК`);
    const full = payload.pagination_complete && payload.list_scan_complete;
    text('completeness', full ? 'Выборка задач полная' : 'Проверена только часть группы');
    el('completeness').classList.toggle('warning', !full);
    text('task-count', payload.tasks_checked);
    text('pages', `${payload.pages_checked} страниц · ${full ? 'полная выборка' : 'с ограничением'}`);
    text('completed', payload.status_codes?.['5'] ?? 0);
    text('overdue', payload.overdue_open_count);
    text('soon', payload.due_in_7_days_count);
    text('roster', payload.list91_employee_count);
    text('audited', payload.tasks_with_list91_auditor);
    text('unknown', payload.tasks_with_unknown_auditors);
    text('human', payload.tasks_with_nontechnical_roster_auditor ?? 'Не определено');
    text('roster-note', payload.technical_exclusions_verified ?
      'Две известные технические учётные записи исключены из отдельного счётчика; персональные права всё ещё не проверены.' :
      'Технические учётные записи не удалось однозначно исключить. Счётчик нетехнических совпадений не рассчитывается.');
    const container = el('statuses');
    container.replaceChildren();
    const entries = Object.entries(payload.status_codes ?? {}).sort(([a], [b]) => Number(a) - Number(b));
    const count = Math.max(1, payload.tasks_checked);
    for (const [code, qty] of entries) {
      const group = document.createElement('div'); group.className = 'status-row';
      const head = document.createElement('div'); head.className = 'status-head';
      const name = document.createElement('span'); name.textContent = labels[code] ?? `Статус ${code}`;
      const n = document.createElement('b'); n.textContent = String(qty);
      head.append(name, n);
      const track = document.createElement('div'); track.className = 'track';
      const bar = document.createElement('div'); bar.className = 'barfill';
      bar.style.width = `${Math.max(0, Math.min(100, qty / count * 100))}%`;
      track.append(bar); group.append(head, track); container.append(group);
    }
    el('body').hidden = false;
    text('finalnote', payload.notice);
  }
  async function load() {
    const token = el('token').value.trim();
    if (!token) { showStatus('Введите тестовый API-токен.', true); return; }
    const button = el('load'); button.disabled = true;
    showStatus('Читаем последний сохранённый снимок…');
    try {
      const response = await fetch('/controller-pilot-test/overview/group734/data', {
        headers: {Authorization: 'Bearer ' + token}, cache: 'no-store'
      });
      const data = await response.json();
      if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`);
      if (data.group_id !== 734 || data.list_id !== 91) throw Error('Ответ не соответствует проверяемой группе');
      render(data);
      showStatus('Снимок успешно загружен. Для обновления данных из Битрикс24 нужен отдельный серверный запуск.');
    } catch (error) {
      showStatus(error instanceof Error ? error.message : 'Не удалось получить сводку', true);
    } finally { button.disabled = false; }
  }
  el('load').addEventListener('click', load);
  el('token').addEventListener('keydown', event => { if (event.key === 'Enter') load(); });
})();
