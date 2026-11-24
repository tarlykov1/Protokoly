'use strict';
const $=id=>document.getElementById(id);
const {groups,csrf}=JSON.parse($('config').textContent);
const fields=['source','group','event','person','query','from','until','dueFrom','dueTo'];
const results=new Map();let zone='',generation=0;
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
  const width=Math.max(430,points.length*96), left=42, bottom=140, top=20;
  const max=percent?100:Math.max(1,...points.map(([,v])=>v||0));
  svg.setAttribute('viewBox',`0 0 ${width} 175`);svg.style.minWidth=Math.min(width,points.length*75)+'px';
  svg.setAttribute('role','img');svg.setAttribute('aria-label',percent?'Динамика ИД':'Число закрытых поручений');
  function draw(tag,attrs,parent=svg){
    const n=document.createElementNS(svg.namespaceURI,tag);
    for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);
    parent.append(n);return n;
  }
  const grad=draw('linearGradient',{id:'fill-'+target,x2:'0%',y2:'100%'},draw('defs',{}));
  const color=percent?'#7453cb':'#208399';
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
    draw('text',{x,y:164,'text-anchor':'middle',fill:'#4a5871'}).textContent=label;
    if(v==null){paint();continue;}
    const y=bottom-(bottom-top)*v/max;segment.push([x,y]);markers.push({x,y,label,v});
  }
  paint();
  for(const {x,y,label,v} of markers){
    const dot=draw('circle',{cx:x,cy:y,r:5,fill:color,stroke:'white','stroke-width':2});
    draw('title',{},dot).textContent=label+' · '+(percent?pct(v):v+' шт.');
    draw('text',{x,y:y-8,'text-anchor':'middle',fill:color}).textContent=percent?pct(v):v;
  }
  box.append(svg);
}
function chartBars(id,entries,complete,empty){
  const box=$(id);box.replaceChildren();
  if(!complete){box.append(elem('p','Ожидаются данные выбранных групп'));return;}
  if(!entries.length){box.append(elem('p',empty));return;}
  const scale=Math.max(1,...entries.map(([,v])=>v||0));
  for(const [name,value] of entries){
    const row=elem('div');row.className='bar-row';
    const line=elem('div');line.className='bar-label';line.append(elem('span',name),elem('b',fmt(value)));
    const track=elem('div');track.className='bar-track';
    if(value!=null){const fill=elem('i');fill.style.width=100*value/scale+'%';track.append(fill);}
    row.append(line,track);box.append(row);
  }
}
function overviewCharts(rows,complete,now){
  const codes={1:'Новая',2:'Ожидает выполнения',3:'Выполняется',4:'Ждёт контроля',5:'Завершена',6:'Отложена',7:'Отклонена'};
  const statuses=new Map(),stages=new Map();
  for(const r of rows){
    const name=codes[r.status]||Model.missing;statuses.set(name,(statuses.get(name)||0)+1);
    if(r.source==='memo'&&Model.zones['Просрочено'](r,now)){
      const stage=r.stage||Model.missing;stages.set(stage,(stages.get(stage)||0)+1);
    }
  }
  const count=fn=>{const values=rows.map(fn);return values.some(v=>v==null)?null:values.filter(Boolean).length;};
  const dates=[['Просрочено',count(r=>Model.zones['Просрочено'](r,now))],
    ['Срок сегодня',count(r=>r.state==null?null:r.state==='open'&&!!r.due&&Model.day(r.due)===Model.day(now))],
    ['Ближайшие 7 суток',count(r=>r.state==null?null:r.state==='open'&&!!r.due&&Date.parse(r.due)>=now&&Date.parse(r.due)<=now+7*86400000)]];
  chartBars('statusGraph',[...statuses],complete,'Нет поручений по фильтрам');
  chartBars('dueGraph',dates,complete,'Нет поручений');
  chartBars('stageGraph',[...stages].sort((a,b)=>b[1]-a[1]),complete,'Нет подтверждённых просрочек в выборке');
  chartBars('controlGraph',[['Контролёр в наблюдателях',count(r=>r.observed_by_controller)],
    ['Есть комментарий контролёра',count(r=>r.reaction)],['Назначен помощник',count(r=>r.assistants==null?null:r.assistants.length>0)]],complete,'Нет поручений');
}
function closedSeries(rows,period){
  const counts=new Map();
  for(const r of rows){
    if(r.state==null || (r.state==='done'&&!r.closed))return [];
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
  const metrics=Model.metrics(rows,complete);
  $('kpis').replaceChildren(...['ИД · исполнено / актуальные','Закрыты в срок / все исполненные','Неактуальные поручения'].map((label,i)=>{
    const el=elem('div',label);el.append(elem('strong',i<2?pct(metrics[i]):fmt(metrics[i])));return el;
  }));
  if(!complete)$('kpis').append(elem('p','Неполный охват источников'));
  overviewCharts(rows,complete,now);
  plot(complete?closedSeries(rows,$('period').value):[], 'closedChart', false);
  $('zones').replaceChildren(...Object.entries(Model.zones).map(([label,fn])=>{
    const values=rows.map(r=>fn(r,now)),n=values.filter(x=>x===true).length,u=values.filter(x=>x==null).length;
    const b=elem('button',label+' · '+(u===values.length&&u?'Нет данных':complete||n?n:'—')+(u?' (+'+u+' без данных)':''));
    b.setAttribute('aria-pressed',zone===label);b.onclick=()=>{zone=zone===label?'':label;render();};return b;
  }));
  const shown=rows.filter(r=>!zone||Model.zones[zone](r,now)===true);
  $('regTitle').textContent='Реестр поручений · '+shown.length+(complete?'':' по загруженным группам');
  $('body').replaceChildren(...shown.map(r=>{
    const tr=elem('tr'),b=elem('button','#'+r.id+' '+(r.title||''));b.onclick=()=>openDetail(r);
    const td=elem('td');td.append(b);tr.append(td);
    for(const v of [r.document,r.event,r.groupName,r.responsible,r.accomplices,r.assistants,r.leader,r.manager,r.stage,dt(r.due),
      {open:'В работе',done:'Исполнено',obsolete:'Неактуально'}[r.state],r.reaction,r.unread])tr.append(elem('td',fmt(v)));
    return tr;
  }));
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
  const content=$('detail').querySelector('article');content.replaceChildren(elem('h2',r.title),elem('h3','История сроков'));
  content.append(elem('p',r.history?'Переносов · '+r.history.moves:Model.missing));
  for(const h of r.history?.dates||[])content.append(elem('p',dt(h.at)+' · '+(h.from||'Без срока')+' → '+(h.to||'Без срока')));
  content.append(elem('h3','Изменения'));for(const h of r.history?.changes||[])content.append(elem('p',dt(h.at)+' · '+h.field));
  content.append(elem('h3','Комментарии'),elem('p','Реакция контролёра · '+fmt(r.reaction)));
  $('detail').showModal();
  const pending=elem('p','Загрузка комментариев…');content.append(pending);
  let detail;
  try {detail=await api('detail',r.group,{task:r.id});}
  catch(e){pending.textContent=e.message;return;}
  if(request!==detailRequest||!$('detail').open)return;
  pending.remove();
  if(!detail.comments?.length)content.append(elem('p',detail.comments?'Комментариев нет':Model.missing));
  for(const c of detail.comments||[])content.append(elem('strong',c.author+' · '+dt(c.at)),elem('p',c.text));
  if(detail.marker!=null)api('mark',r.group,{task:r.id,marker:detail.marker}).then(()=>{r.unread=false;render();}).catch(e=>content.append(elem('p',e.message)));
}
function syncWidth(){$('upper').firstElementChild.style.width=$('lower').scrollWidth+'px';}
$('upper').onscroll=()=>{$('lower').scrollLeft=$('upper').scrollLeft;};
$('lower').onscroll=()=>{$('upper').scrollLeft=$('lower').scrollLeft;};
new ResizeObserver(syncWidth).observe($('lower').querySelector('table'));
for(const g of groups)$('group').add(new Option(g.name,g.id));
for(const id of [...fields,'period'])$(id).oninput=render;
$('clear').onclick=()=>{for(const id of fields)$(id).value='';zone='';render();};
$('refresh').onclick=load;$('close').onclick=()=>$('detail').close();load();
