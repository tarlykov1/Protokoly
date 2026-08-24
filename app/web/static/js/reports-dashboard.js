(() => {
  const colors = ['#2563eb','#16a34a','#f59e0b','#dc2626','#7c3aed'];
  const params = new URLSearchParams(location.search);
  let active = params.get('chart') ? {key: params.get('chart'), value: params.get('segment')} : null;
  const rows = [...document.querySelectorAll('[data-detail-table] tbody tr')];
  let page = 1;
  const render = () => {
    const search = (document.querySelector('[data-table-search]')?.value || '').toLocaleLowerCase('ru');
    const size = +(document.querySelector('[data-page-size]')?.value || 25);
    const filtered = rows.filter(row => {
      const matchesSearch = !search || row.textContent.toLocaleLowerCase('ru').includes(search);
      if (!active) return matchesSearch;
      const {key,value} = active;
      if (key === 'task_status') return matchesSearch && row.dataset.status === value;
      if (key === 'document_type') return matchesSearch && row.dataset.documentType === value;
      if (key === 'data_issue') return matchesSearch && (value === 'ok' ? !row.dataset.dataIssues.trim() : row.dataset.dataIssues.includes(value));
      if (key === 'control') return matchesSearch && row.dataset.control === value;
      return matchesSearch;
    });
    const pages = Math.max(1, Math.ceil(filtered.length / size)); page = Math.min(page, pages);
    rows.forEach(row => row.hidden = true);
    filtered.slice((page - 1) * size, page * size).forEach(row => row.hidden = false);
    const info = document.querySelector('[data-page-info]'); if (info) info.textContent = `${filtered.length} записей · страница ${page} из ${pages}`;
    document.querySelectorAll('[data-chart-key]').forEach(button => button.classList.toggle('active', !!active && button.dataset.chartKey === active.key && button.dataset.chartValue === active.value));
  };
  document.querySelectorAll('.donut-panel').forEach(panel => {
    const buttons = [...panel.querySelectorAll('[data-count]')], total = buttons.reduce((sum,b) => sum + +b.dataset.count, 0) || 1;
    let cursor = 0; const stops = buttons.map((button,index) => { const from=cursor; cursor += +button.dataset.count * 100 / total; button.style.setProperty('--chart-color', colors[index]); return `${colors[index]} ${from}% ${cursor}%`; });
    panel.querySelector('[data-donut]').style.background = `conic-gradient(${stops.join(',')})`;
    buttons.forEach(button => button.addEventListener('click', () => { active={key:button.dataset.chartKey,value:button.dataset.chartValue}; page=1; params.set('chart',active.key); params.set('segment',active.value); history.replaceState({},'',`${location.pathname}?${params}`); render(); }));
  });
  document.querySelector('[data-reset-chart]')?.addEventListener('click', () => { active=null; params.delete('chart'); params.delete('segment'); history.replaceState({},'',params.size?`${location.pathname}?${params}`:location.pathname); render(); });
  document.querySelector('[data-table-search]')?.addEventListener('input', () => { page=1; render(); });
  document.querySelector('[data-page-size]')?.addEventListener('change', () => { page=1; render(); });
  document.querySelector('[data-page-prev]')?.addEventListener('click', () => { page=Math.max(1,page-1); render(); });
  document.querySelector('[data-page-next]')?.addEventListener('click', () => { page+=1; render(); });
  document.querySelectorAll('[data-quick]').forEach(button => button.addEventListener('click', () => { const now=new Date(), monday=new Date(now); monday.setDate(now.getDate()-((now.getDay()+6)%7)); let start=monday,end=new Date(monday); if(button.dataset.quick==='last-week'){start=new Date(monday);start.setDate(start.getDate()-7);end=new Date(monday);end.setDate(end.getDate()-1)} else if(button.dataset.quick==='month'){start=new Date(now.getFullYear(),now.getMonth(),1);end=new Date(now.getFullYear(),now.getMonth()+1,0)} else end.setDate(end.getDate()+6); if(button.dataset.quick==='overdue'){params.set('overdue','true')}else{params.set('period_start',start.toISOString().slice(0,10));params.set('period_end',end.toISOString().slice(0,10));params.set('weekly','true')} location.search=params; }));
  render();
})();
