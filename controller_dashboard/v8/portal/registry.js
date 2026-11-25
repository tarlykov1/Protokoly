'use strict';

const Registry = (() => {
  const control = id => document.getElementById(id);
  const query = control('registryQuery');
  const mode = control('registryMode');
  const order = control('registryOrder');
  let source = [], visible = [], now = 0, complete = false, openTask, resize;
  const signalChecks = [
    ['Просрочено', 'danger'],
    ['Срок сегодня', 'warning'],
    ['Ждёт контроля', 'warning'],
    ['Без активности более 7 рабочих дней', 'warning'],
    ['Старт позже 48 рабочих часов', 'warning'],
    ['Неоднократный перенос срока', 'warning'],
    ['Новый комментарий', 'info']
  ];

  function signalsFor(row) {
    const signals = [];
    let unknown = false;
    for (const [label, tone] of signalChecks) {
      const value = Model.zones[label](row, now);
      if (value == null) unknown = true;
      if (value !== true) continue;
      let text = label;
      if (label === 'Просрочено') {
        const elapsed = (Date.parse(Model.day(now)) - Date.parse(Model.day(row.due))) / 86400000;
        text = elapsed > 0 ? 'Просрочено · ' + elapsed + ' дн.' : 'Просрочено сегодня';
      }
      signals.push({ label, text, tone });
    }
    const label=Model.closureLabel(row);
    if(label)signals.push({label,text:label,tone:'info'});
    return { signals, unknown };
  }

  function dateOrder(a, b, descending = false) {
    const first = Date.parse(a), second = Date.parse(b);
    if (!Number.isFinite(first)) return Number.isFinite(second) ? 1 : 0;
    if (!Number.isFinite(second)) return -1;
    return descending ? second - first : first - second;
  }

  function searchable(row) {
    return [row.id, row.title, row.document, row.event, row.groupName, row.stage, row.responsible,
      ...(row.accomplices || []), ...(row.assistants || [])].filter(Boolean).join(' ').toLocaleLowerCase('ru');
  }

  function render() {
    if (!openTask) return;
    const needle = query.value.trim().toLocaleLowerCase('ru').replace(/^#(?=\d)/, '');
    const items = [];
    for (const row of source) {
      if (needle && !searchable(row).includes(needle)) continue;
      const { signals, unknown } = signalsFor(row);
      const overdue = signals.some(s => s.label === 'Просрочено');
      const problem = signals.some(s => s.tone !== 'info');
      if (mode.value === 'overdue' && !overdue) continue;
      if (mode.value === 'problems' && !problem) continue;
      items.push({ row, signals, unknown, overdue, problem });
    }
    if (order.value === 'risk') {
      items.sort((a, b) => Number(b.overdue) - Number(a.overdue) || Number(b.problem) - Number(a.problem) ||
        dateOrder(a.row.due, b.row.due));
    } else if (order.value === 'due') {
      items.sort((a, b) => dateOrder(a.row.due, b.row.due));
    } else if (order.value === 'assigned') {
      items.sort((a, b) => dateOrder(a.row.assigned, b.row.assigned, true));
    }
    visible = items.map(item => item.row);
    control('regTitle').textContent = 'Реестр поручений · ' + visible.length + (complete ? '' : ' по загруженным группам');
    control('registryCount').textContent = 'Показано ' + visible.length + ' из ' + source.length +
      (complete ? '' : ' по загруженным группам');
    const body = control('body');
    const fragment = document.createDocumentFragment();
    for (const { row, signals, unknown, overdue } of items) {
      const tr = document.createElement('tr');
      if (overdue) tr.classList.add('registry-overdue');
      const title = document.createElement('button');
      title.className = 'registry-task';
      title.textContent = '#' + row.id + ' ' + (row.title || '');
      title.addEventListener('click', () => openTask(row));
      const cell=value=>{const td=tr.insertCell();td.textContent=fmt(value);return td;};
      cell(dt(row.assigned));cell(dt(row.due));
      const badges = tr.insertCell();
      badges.className = 'registry-signals';
      for (const { text, tone } of signals) {
        const badge = document.createElement('span');
        badge.className = 'signal signal-' + tone;
        badge.textContent = text;
        badges.append(badge);
      }
      if (!signals.length) badges.textContent = unknown ? 'Нет данных' : '—';
      const state = { open: 'В работе', done: 'Исполнено', obsolete: 'Неактуально' }[row.state];
      const responsible=cell(row.responsible);
      if(row.accomplices?.length)responsible.append(elem('small','Соисполнители: '+row.accomplices.join(', ')));
      cell(row.assistants);
      const task=tr.insertCell();
      task.className='registry-document';
      task.append(elem('b',fmt(row.document)),title);
      cell(row.reaction==null?'Нет данных':row.reaction?'Есть комментарий':'Комментария нет');
      for(const value of [row.event,row.groupName,row.leader,row.manager,row.stage,state,row.unread])cell(value);
      fragment.append(tr);
    }
    body.replaceChildren(fragment);
    resize();
  }

  query.addEventListener('input', render);
  mode.addEventListener('change', render);
  order.addEventListener('change', render);
  control('registryReset').addEventListener('click', () => {
    query.value = '';
    mode.value = 'all';
    order.value = 'source';
    render();
  });

  return {
    visibleRows: () => visible,
    update(rows, time, isComplete, onOpen, onResize) {
      source = rows;
      now = time;
      complete = isComplete;
      openTask = onOpen;
      resize = onResize;
      render();
    }
  };
})();
