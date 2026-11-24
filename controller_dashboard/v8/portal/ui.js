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
function plot(points){
  const box=$('chart');box.replaceChildren();
  if(!points.length){box.textContent='Нет сопоставимых срезов';return;}
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),width=Math.max(420,points.length*105);
  svg.setAttribute('width',width);svg.setAttribute('height',165);svg.setAttribute('aria-label','ИД по периодам, в процентах');
  function draw(tag,attrs,label){const e=document.createElementNS(svg.namespaceURI,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(label)e.textContent=label;svg.append(e);}
  let prev=null;
  for(const [i,[label,value]] of points.entries()){
    const x=55+i*(width-110)/Math.max(1,points.length-1),y=120-(value??0);
    draw('text',{x,y:153,'text-anchor':'middle'},label);
    if(value!==null){
      if(prev)draw('line',{x1:prev.x,y1:prev.y,x2:x,y2:y,stroke:'#126660','stroke-width':3});
      draw('circle',{cx:x,cy:y,r:4,fill:'#126660'});
    }
    draw('text',{x,y:value===null?80:y+16,'text-anchor':'middle'},pct(value));prev=value===null?null:{x,y};
  }
  box.append(svg,elem('p','Последний совместный срез периода. В расчёте – доступные сейчас поручения, присутствовавшие в этом срезе. До первой выгрузки история отсутствует.'));
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
  const counts=new Map();for(const r of rows)if(r.source==='memo'&&Model.zones['Просрочено'](r,now)){
    const s=r.stage||Model.missing;counts.set(s,(counts.get(s)||0)+1);
  }
  $('stages').textContent='Просрочено по стадиям МЕМО (загруженные поручения) · '+([...counts].map(([k,v])=>k+' — '+v).join(' / ')||'Нет подтверждённых просрочек');
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
