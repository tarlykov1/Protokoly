'use strict';
const codes={1:'Новая',2:'Ожидает выполнения',3:'Выполняется',4:'Ждёт контроля',5:'Завершена',6:'Отложена',7:'Отклонена'};
const $=id=>document.getElementById(id);
const {groups,csrf}=JSON.parse($('config').textContent);
const fields=['source','group','event','person','query','from','until','dueFrom','dueTo'];
const results=new Map();let zone='',activeStage,generation=0;
function elem(tag,value){const el=document.createElement(tag);if(value!==undefined)el.textContent=value;return el;}
function fmt(v){
  if(v==null)return Model.missing;
  if(Array.isArray(v))return v.length?v.join(', '):'Нет';
  if(typeof v==='boolean')return v?'Да':'Нет';
  return String(v);
}
const dt=v=>v?new Date(v).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'}):Model.missing;
const pct=v=>v==null?Model.missing:v.toLocaleString('ru-RU')+' %';
async function api(op,group,more={}){
  const res=await fetch('api.php',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:new URLSearchParams({op,group,sessid:csrf,...more}),cache:'no-store'});
  const data=await res.json().catch(()=>({error:'Ответ сервера недоступен'}));
  if(!res.ok||data.error)throw Error(data.error||'Ошибка '+res.status);
  return data;
}
async function load(){
  const gen=++generation;results.clear();render();$('refresh').disabled=true;
  // Sequential requests avoid bursts against the production reporting source.
  const waiting=[...groups];
  for(let attempt=0;waiting.length&&attempt<45;attempt++){
    for(const g of [...waiting]){
      if(gen!==generation)return;
      try{
        const data=await api('group',g.id,{poll:attempt}); results.set(g.id,data);
        if(data.status==='ready')waiting.splice(waiting.indexOf(g),1);
      }catch(e){results.set(g.id,{status:'error',error:e.message});waiting.splice(waiting.indexOf(g),1);}
      render();
    }
    if(waiting.length)await new Promise(resolve=>setTimeout(resolve,4000));
  }
  for(const g of waiting)results.set(g.id,{status:'error',error:'Отчёт ещё не готов. Повторите обновление.'});
  $('refresh').disabled=false; render();
}
function plot(points, target='chart', percent=true){
  const box=$(target); box.replaceChildren();
  if(!points.length || points.every(([,value])=>value==null)){
    box.append(elem('p',percent?'Нет сопоставимых срезов ИД':'Нет данных о закрытиях по периодам'));
    return;
  }
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  const width=600, left=42, bottom=140, top=20;
  const max=percent?100:Math.max(1,...points.map(([,v])=>v||0));
  svg.setAttribute('viewBox',`0 0 ${width} 175`);
  svg.setAttribute('role','img');svg.setAttribute('aria-label',percent?'Динамика ИД':'Число закрытых поручений');
  function draw(tag,attrs,parent=svg){
    const n=document.createElementNS(svg.namespaceURI,tag);
    for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);
    parent.append(n);return n;
  }
  const grad=draw('linearGradient',{id:'fill-'+target,x2:'0%',y2:'100%'},draw('defs',{}));
  const color='#7160da';
  draw('stop',{offset:'0%','stop-color':color,'stop-opacity':'.35'},grad);
  draw('stop',{offset:'100%','stop-color':color,'stop-opacity':'.02'},grad);
  const ticks=percent?4:Math.min(4,max);
  for(let i=0;i<=ticks;i++){
    const val=percent?max*i/ticks:Math.round(max*i/ticks),y=bottom-(bottom-top)*val/max;
    draw('line',{x1:left,x2:width-20,y1:y,y2:y,stroke:'#e3e7f1'});
    draw('text',{x:4,y:y+4,fill:'#5f6c86'}).textContent=val;
  }
  let segment=[];
  function paint(){
    if(!segment.length)return;
    const coords=segment.map(p=>p.join(',')).join(' ');
    draw('polygon',{points:segment[0][0]+','+bottom+' '+coords+' '+segment.at(-1)[0]+','+bottom,fill:'url(#fill-'+target+')'});
    draw('polyline',{points:coords,stroke:color,'stroke-width':3,fill:'none','stroke-linejoin':'round'});
    segment=[];
  }
  const markers=[];
  for(const [i,[label,v]] of points.entries()){
    const x=points.length===1?width/2:left+i*(width-left-35)/(points.length-1);
    if(i===points.length-1 || (i%Math.ceil(points.length/5)===0 && i<points.length-Math.ceil(points.length/10)))draw('text',{x,y:164,'text-anchor':'middle',fill:'#4a5871'}).textContent=label;
    if(v==null){paint();continue;}
    const y=bottom-(bottom-top)*v/max;segment.push([x,y]);markers.push({x,y,label,v});
  }
  paint();
  for(const {x,y,label,v} of markers){
    const dot=draw('circle',{cx:x,cy:y,r:points.length>25?2.5:4,fill:'white',stroke:color,'stroke-width':2});
    draw('title',{},dot).textContent=label+' · '+(percent?pct(v):v+' шт.');
    if(points.length<=12)draw('text',{x,y:y-8,'text-anchor':'middle',fill:color}).textContent=percent?pct(v):v;
  }
  box.append(svg);
}
function chartBars(id,entries,complete,empty,percent=false){
  const box=$(id);box.replaceChildren();
  if(!complete){box.append(elem('p','Ожидаются данные выбранных групп'));return;}
  if(!entries.length){box.append(elem('p',empty));return;}
  const scale=percent?100:Math.max(1,...entries.map(([,v])=>v||0));
  for(const [name,value] of entries){
    const row=elem('div');row.className='bar-row';
    const line=elem('div');line.className='bar-label';line.append(elem('span',name),elem('b',percent?pct(value):fmt(value)));
    const track=elem('div');track.className='bar-track';
    if(value!=null){const fill=elem('i');fill.style.width=100*value/scale+'%';track.append(fill);}
    row.append(line,track);box.append(row);
  }
}
function confirmedCount({yes,unknown}){
  if(!unknown)return fmt(yes);
  return yes?'≥ '+yes:Model.missing;
}
function coverageNote(n){
  return n?' · без подтверждения: '+n:'';
}
function renderCards(rows,complete,now){
  const {execution,timely,active,discipline,onTime}=Model.kpiCoverage(rows);
  const makeCount=(label,test,detail,tone)=>{
    const tally=Model.tally(rows,test);
    return [label,complete?confirmedCount(tally):Model.missing,complete?detail+coverageNote(tally.unknown):detail,tone];
  };
  const considered=timely.total-timely.unknown;
  const cards=[
    ['ИД · исполнено / актуальные',complete?pct(discipline):Model.missing,
      complete?'Подтверждено: '+execution.yes+' из '+active+' актуальных'+coverageNote(execution.unknown):'Ожидаются данные групп','discipline'],
    ['Закрыты в срок / все исполненные',complete?pct(onTime):Model.missing,
      complete?'Среди проверенных: '+timely.yes+' из '+considered+coverageNote(execution.unknown+timely.unknown):'Ожидаются данные групп','timeliness'],
    makeCount('Исполнено',r=>r.state==null?null:r.state==='done','По главному ответственному','done'),
    makeCount('Просрочено',r=>Model.zones['Просрочено'](r,now),'Незавершённые поручения','overdue'),
    makeCount('Срок в ближайшие 5 дней',r=>Model.upcoming(r,now,5),'Включая сегодняшний день','upcoming'),
  ];
  if(complete && execution.unknown) cards[0][0]='ИД по подтверждённым поручениям';
  if(complete && (execution.unknown||timely.unknown)) cards[1][0]='Закрыты в срок · по подтверждённым';
  const obsolete=confirmedCount(Model.tally(rows,r=>r.state==null?null:r.state==='obsolete'));
  const box=$('kpis');
  box.replaceChildren(...cards.map(([label,value,detail,tone])=>{
    const item=elem('div');item.className='kpi-item kpi-'+tone;
    item.append(elem('span',label),elem('strong',value),elem('small',detail));return item;
  }));
  if(!complete)box.append(elem('p','Неполный охват источников'));
  return obsolete;
}
function portfolio(rows,scope,complete,obsolete){
  const bySource=Model.groupRows(rows,r=>r.source);
  const names={memo:'МЕМО',protocol:'Протоколы'};
  const sources=[...new Set(scope.map(g=>g.source))];
  chartBars('portfolio',sources.map(key=>[names[key]||key,bySource.get(key)?.length||0]),complete,'Нет доступных групп');
  if(complete)$('portfolio').append(elem('p','Неактуальных поручений: '+fmt(obsolete)));
  const groupsById=Model.groupRows(rows,r=>r.group);
  const entries=scope.map(group=>{
    const k=Model.kpiCoverage(groupsById.get(group.id)||[]);
    return [group.name+(k.execution.unknown?' · по подтверждённым ('+k.active+' актуальных, без подтверждения: '+k.execution.unknown+')':''),k.discipline];
  });
  chartBars('groupDiscipline',entries,complete,'Нет доступных групп',true);
}
const stageStyles = new Map([
  ['К выполнению', ['#1997a6', '●']],
  ['Выполняется', ['#377ed7', '▶']],
  ['На доработке', ['#865dce', '↻']],
  ['На приёмке', ['#bb5288', '◆']],
  ['Завершена', ['#20976d', '✓']],
  ['Неактуально', ['#657487', '−']]
]);
const stageAliases = new Map([
  ['в работе','Выполняется'], ['выполнены','Завершена'], ['выполненные задачи','Завершена'],
  ['неактуальные задачи','Неактуально'], ['на приемке','На приёмке'],
  ...Array.from(stageStyles.keys(), name => [name.toLowerCase(), name])
]);
function displayStage(row){
  const name=row.stage?.trim();
  return stageAliases.get(name?.toLowerCase()) || name || 'Стадия не указана';
}
function deadlineSplit(rows,closed,now){
  let late=0, timely=0;
  for(const row of rows){
    const due=Date.parse(row.due);
    const at=closed?Date.parse(row.closed):now;
    if(row.state!==(closed?'done':'open') || !Number.isFinite(due) || !Number.isFinite(at))continue;
    if(at>due)late++;else timely++;
  }
  return {lines:[[closed?'Закрыто с просрочкой':'Срок истёк',late],[closed?'Закрыто в срок':'Срок не истёк',timely]],other:rows.length-late-timely};
}
function selectStage(key){
  $('registryMode').value='all';
  riskFilter=null;zone='';activeStage=activeStage===key?undefined:key;
  render();$('regTitle').scrollIntoView({block:'nearest'});
}
function renderStages(rows,complete,now){
  const box=$('stageRing'),cards=$('stageCards');
  box.replaceChildren();cards.replaceChildren();
  $('stageVolume').textContent=complete?'Задач: '+rows.length:'';
  if(!complete||!rows.length){
    box.append(elem('p',complete?'Нет поручений по фильтрам':'Ожидаются данные выбранных групп'));return;
  }
  const grouped=Model.groupRows(rows,displayStage);
  const donut=elem('div'),total=elem('strong',rows.length),legend=elem('div'),stops=[];
  donut.className='stage-donut';total.className='stage-total';legend.className='stage-legend';
  donut.setAttribute('aria-hidden','true');donut.append(total);
  let cumulative=0;
  const extras=[...grouped.keys()].filter(key=>!stageStyles.has(key)).sort();
  for(const key of [...stageStyles.keys(),...extras]){
    const batch=grouped.get(key)||[], label=key;
    const [color,icon]=stageStyles.get(key)||['#798591','•'];
    const size=batch.length,share=100*size/rows.length;
    if(size)stops.push(color+' '+cumulative+'% '+(cumulative+share)+'%');cumulative+=share;
    const line=elem('div'),dot=elem('i'),button=elem('button');
    dot.className='stage-dot';dot.style.background=color;
    line.append(dot,elem('span',label),elem('b',size+' / '+pct(Math.round(share*10)/10)));legend.append(line);
    button.type='button';button.className='stage-card';button.style.setProperty('--stage-color',color);
    button.setAttribute('aria-pressed',activeStage===key?'true':'false');
    button.setAttribute('aria-label',label+' · '+size+' · показать в реестре');
    button.disabled=!size;button.onclick=()=>selectStage(key);
    const heading=elem('span',label);heading.className='stage-heading';heading.dataset.icon=icon;
    const values=elem('div');values.className='stage-count';
    values.append(elem('strong',size),elem('small',pct(Math.round(share*10)/10)));
    button.append(heading,values);
    const deadlines=deadlineSplit(batch,key==='Завершена',now);
    for(const [caption,count] of deadlines.lines){
      const item=elem('span');item.className='stage-line';
      const track=elem('i'),fill=elem('i');
      if(count!=null){fill.style.width=(size?100*count/size:0)+'%';track.append(fill);}
      item.append(elem('span',caption),track,elem('b',fmt(count)),elem('small',size?pct(Math.round(count*1000/size)/10):'—'));button.append(item);
    }
    if(deadlines.other){const note=elem('small','Другой/неизвестный срок: '+deadlines.other);note.className='stage-other';button.append(note);}
    cards.append(button);
  }
  donut.style.background='conic-gradient('+stops.join(',')+')';
  const reset=elem('button',activeStage===undefined?'Все стадии выбраны':'Сбросить выбор стадии');
  reset.disabled=activeStage===undefined;
  reset.onclick=()=>selectStage(activeStage);
  const head=elem('div');head.className='stage-intro';
  head.append(elem('b','Стадии и состояние задач'),elem('small','С учётом риска и просрочки'));
  box.append(head,donut,legend,reset);
}

let riskFilter=null;
function riskGroups(rows,now,complete){
  const overdue=r=>Model.zones['Просрочено'](r,now);
  const days=r=>(Date.parse(Model.day(now))-Date.parse(Model.day(r.due)))/86400000;
  const definitions=[['Все просроченные',overdue]];
  for(const stage of [...new Set(rows.filter(r=>overdue(r)===true).map(r=>r.stage))].filter(Boolean).sort()){
    definitions.push(['Просрочено · '+stage,r=>r.stage===stage?overdue(r):false]);
  }
  definitions.push(['Просрочка до 7 дней',r=>{const late=overdue(r);return late===true?days(r)<=7:late;}],
    ['Более 7 дней',r=>Model.overdueWeek(r,now)]);
  const box=$('riskChips');box.replaceChildren();
  let selected;
  for(const [label,test] of definitions){
    const b=elem('button');b.append(elem('span',label),elem('b',complete?confirmedCount(Model.tally(rows,test)):Model.missing));
    b.setAttribute('aria-pressed',riskFilter===label);
    if(riskFilter===label)selected=test;
    b.onclick=()=>{$('registryMode').value='all';riskFilter=riskFilter===label?null:label;zone='';activeStage=undefined;render();$('registry').scrollIntoView();};
    box.append(b);
  }
  if(!selected)riskFilter=null;
  return selected;
}
function overviewCharts(rows,complete,now){

  const statuses=new Map(),stages=new Map();
  for(const r of rows){
    const name=codes[r.status]||Model.missing;statuses.set(name,(statuses.get(name)||0)+1);
    if(r.source==='memo'&&Model.zones['Просрочено'](r,now)){
      const stage=r.stage||Model.missing;stages.set(stage,(stages.get(stage)||0)+1);
    }
  }
  const count=fn=>{const values=rows.map(fn);return values.some(v=>v==null)?null:values.filter(Boolean).length;};
  const dates=[['Просрочено',count(r=>Model.zones['Просрочено'](r,now))],
    ['Срок сегодня',count(r=>Model.zones['Срок сегодня'](r,now))],
    ['Ближайшие 7 суток',count(r=>Model.upcoming(r,now,7))]];
  chartBars('statusGraph',[...statuses],complete,'Нет поручений по фильтрам');
  chartBars('dueGraph',dates,complete,'Нет поручений');
  chartBars('stageGraph',[...stages].sort((a,b)=>b[1]-a[1]),complete,'Нет подтверждённых просрочек в выборке');
  chartBars('controlGraph',[['Контролёр в наблюдателях',count(r=>r.observed_by_controller)],
    ['Есть комментарий контролёра',count(r=>r.reaction)],['Назначен помощник',count(r=>r.assistants==null?null:r.assistants.length>0)]],complete,'Нет поручений');
}
function closedSeries(rows,period){
  const counts=new Map();
  for(const r of rows){
    if(!Number.isFinite(Date.parse(r.closed)))continue;
    if(r.state!=='done')continue;
    const key=Model.bucket(Model.day(r.closed),period);
    counts.set(key,(counts.get(key)||0)+1);
  }
  return [...counts].sort(([a],[b])=>a.localeCompare(b));
}
function options(id,values){$(id).replaceChildren(...[...new Set(values.filter(Boolean))].sort().map(x=>new Option(x,x)));}
function render(){
  const f=Object.fromEntries(fields.map(k=>[k,$(k).value]));
  const scope=groups.filter(g=>(!f.source||g.source===f.source)&&(!f.group||String(g.id)===f.group));
  const histories={},all=[];
  const complete=scope.length>0&&scope.every(g=>results.get(g.id)?.status==='ready');
  $('sources').textContent=groups.map(g=>{
    const v=results.get(g.id);return g.name+' · '+(v?.status==='ready'?'Выгрузка '+dt(v.at)+' · проверка задач '+dt(v.checked):v?.error||'Ожидается выгрузка');
  }).join('\n');
  for(const g of scope){
    const pack=results.get(g.id);if(pack?.status!=='ready')continue;
    histories[g.id]=pack.history;
    for(const row of pack.rows)all.push(Object.assign(row,{source:g.source,group:g.id,groupName:g.name}));
  }
  options('people',all.flatMap(r=>[r.responsible,...r.accomplices]));options('events',all.map(r=>r.event));
  const rows=all.filter(r=>Model.match(r,f)),now=Date.now();
  if(activeStage!==undefined&&!rows.some(r=>displayStage(r)===activeStage))activeStage=undefined;
  $('csv').disabled=!complete;
  const obsolete=renderCards(rows,complete,now);
  $('volume').textContent=(complete?'':'Загружено · ')+'Поручений: '+rows.length+scope.filter(g=>results.get(g.id)?.at).map(g=>' · '+g.name+' '+dt(results.get(g.id).at).split(',')[0]).join('');
  portfolio(rows,scope,complete,obsolete);
  renderStages(rows,complete,now);
  const attentionLabel='Просрочка более 7 дней';
  const attention=Model.tally(rows,r=>Model.overdueWeek(r,now));
  $('attentionCount').textContent=complete?confirmedCount(attention):Model.missing;
  $('attentionCount').title=complete&&attention.unknown?'Без подтверждения: '+attention.unknown:'';
  $('attentionOpen').setAttribute('aria-pressed',zone===attentionLabel?'true':'false');
  $('attentionOpen').onclick=()=>{
    $('registryMode').value='all';
    activeStage=undefined;
    riskFilter=null;zone=zone===attentionLabel?'':attentionLabel;
    render();$('regTitle').scrollIntoView({block:'nearest'});
  };
  for(const button of $('periodButtons').querySelectorAll('[data-period]')){
    button.setAttribute('aria-pressed',button.dataset.period===$('period').value?'true':'false');
  }
  overviewCharts(rows,complete,now);
  plot(complete?closedSeries(rows,$('period').value):[], 'closedChart', false);
  if(complete){
    const missing=rows.filter(r=>r.state==null||(r.state==='done'&&!Number.isFinite(Date.parse(r.closed)))).length;
    if(missing)$('closedChart').append(elem('small','Учтены подтверждённые исполнения с датой закрытия · без подтверждения: '+missing));
  }
  $('zones').replaceChildren(...Object.entries(Model.zones).map(([label,fn])=>{
    const values=rows.map(r=>fn(r,now)),n=values.filter(x=>x===true).length,u=values.filter(x=>x==null).length;
    const b=elem('button',label+' · '+(u===values.length&&u?'Нет данных':complete||n?n:'—')+(u?' (+'+u+' без данных)':''));
    b.setAttribute('aria-pressed',zone===label);b.onclick=()=>{$('registryMode').value='all';riskFilter=null;zone=zone===label?'':label;render();};return b;
  }));
  const risk=riskGroups(rows,now,complete);
  const shown=rows.filter(r=>(!risk||risk(r)===true)&&(!zone||Model.zones[zone](r,now)===true)&&(activeStage===undefined||displayStage(r)===activeStage));
  Registry.update(shown,now,complete,openDetail,syncWidth);
  const series=items=>complete?Model.series(items,histories,scope.map(g=>g.id),$('period').value):[];
  const points=series(rows);plot(points);
  const table=elem('table'),header=elem('tr');header.append(elem('th','Главный ответственный'));
  for(const [p] of points)header.append(elem('th',p));table.append(header);
  const byUser=new Map();for(const r of rows){if(!byUser.has(r.responsible_id))byUser.set(r.responsible_id,[]);byUser.get(r.responsible_id).push(r);}
  for(const subset of byUser.values()){const tr=elem('tr');tr.append(elem('td',fmt(subset[0].responsible)));for(const [,v] of series(subset))tr.append(elem('td',pct(v)));table.append(tr);}
  $('individual').replaceChildren(table);syncWidth();
}
let detailRequest=0;
async function openDetail(r){
  const request=++detailRequest;
  const content=$('detail').querySelector('article');content.replaceChildren(elem('h2',r.title));
  if(r.controller_closure){
    const closure=r.controller_closure;
    content.append(elem('strong',Model.closureLabel(r)),elem('p',[closure.author,dt(closure.at)].join(' · ')),
      elem('p','Зачтено в ИД главного ответственного · '+fmt(r.responsible)));
  }
  content.append(elem('h3','История сроков'));
  content.append(elem('p',r.history?'Переносов · '+r.history.moves:Model.missing));
  for(const h of r.history?.dates||[])content.append(elem('p',dt(h.at)+' · '+(h.from||'Без срока')+' → '+(h.to||'Без срока')));
  const fields={STATUS:'Статус',TITLE:'Название',STAGE:'Стадия',ACCOMPLICES:'Соисполнители',AUDITORS:'Наблюдатели',RESULT:'Результат',RESULT_EDIT:'Изменён результат',TAGS:'Теги',COMMENT_EDIT:'Изменён комментарий',DEADLINE:'Срок'};
  content.append(elem('h3','Изменения'));
  for(const h of r.history?.changes||[]){
    const parts=[dt(h.at),h.author,fields[h.field]||h.field];
    if(h.field==='STATUS' && h.to) parts.push((codes[h.from]||h.from||'—')+' → '+(codes[h.to]||h.to));
    content.append(elem('p',parts.filter(Boolean).join(' · ')));
  }
  content.append(elem('h3','Комментарии'),elem('p','Реакция контролёра · '+fmt(r.reaction)));
  $('detail').showModal();
  const pending=elem('p','Загрузка комментариев…');content.append(pending);
  let detail;
  try {detail=await api('detail',r.group,{task:r.id});}
  catch(e){pending.textContent=e.message;return;}
  if(request!==detailRequest||!$('detail').open)return;
  pending.remove();
  if(!detail.comments?.length)content.append(elem('p',detail.comments?'Комментариев нет':detail.comments_status==='ambiguous'?'У задачи неоднозначная связь с источником комментариев. Уточните источник в настройках группы.':'Источник комментариев недоступен'));
  for(const c of detail.comments||[])content.append(elem('strong',c.author+' · '+dt(c.at)),elem('p',c.text));
  if(detail.marker!=null)api('mark',r.group,{task:r.id,marker:detail.marker}).then(()=>{r.unread=false;render();}).catch(e=>content.append(elem('p',e.message)));
}
function downloadRegistry(){
  const headers=['ID','Поручение','Документ','Мероприятие','Группа','Ответственный','Соисполнители','Помощники',
    'Руководитель в задаче','Руководитель по оргструктуре','Стадия','Статус Битрикс24','Срок','Состояние','Реакция контролёра','Новый комментарий','Закрытие контролёром','Кто закрыл (контролёр)'];
  const lines=[headers,...Registry.visibleRows().map(r=>[r.id,r.title,r.document,r.event,r.groupName,r.responsible,
    fmt(r.accomplices),fmt(r.assistants),r.leader,r.manager,r.stage,codes[r.status],dt(r.due),
    {open:'В работе',done:'Исполнено',obsolete:'Неактуально'}[r.state],fmt(r.reaction),fmt(r.unread),Model.closureLabel(r),r.controller_closure?.author||''])];
  const blob=new Blob(['\uFEFF',lines.map(line=>line.map(Model.csvCell).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'});
  const url=URL.createObjectURL(blob),link=elem('a');
  link.href=url;link.download='Реестр поручений '+Model.day(Date.now())+'.csv';
  document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function syncWidth(){$('upper').firstElementChild.style.width=$('lower').scrollWidth+'px';}
$('upper').onscroll=()=>{$('lower').scrollLeft=$('upper').scrollLeft;};
$('lower').onscroll=()=>{$('upper').scrollLeft=$('lower').scrollLeft;};
new ResizeObserver(syncWidth).observe($('lower').querySelector('table'));
for(const g of groups)$('group').add(new Option(g.name,g.id));
for(const id of fields)$(id).oninput=()=>{$('registryMode').value='all';render();};
$('period').oninput=render;
$('clear').onclick=()=>{for(const id of fields)$(id).value='';zone='';riskFilter=null;activeStage=undefined;render();};
$('csv').onclick=downloadRegistry;
$('periodButtons').onclick=e=>{
  const button=e.target.closest('[data-period]');
  if(button){$('period').value=button.dataset.period;render();}
};
$('refresh').onclick=load;$('close').onclick=()=>$('detail').close();load();
