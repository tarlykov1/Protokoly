'use strict';
/* Read-only presentation hotfix for Timeline v6. Backend/API/database unchanged. */
(() => {
 const labels = {
   DEADLINE: 'Изменение крайнего срока', COMMENT: 'Комментарий', COMMENT_EDIT: 'Редактирование комментария',
   COMMENT_DEL: 'Удаление комментария', STAGE: 'Стадия задачи', STATUS: 'Статус задачи',
   AUDITORS: 'Наблюдатели', NEW: 'Создание задачи', RESULT: 'Результат выполнения',
   DESCRIPTION: 'Изменение описания поручения', UF_CRM_TASK_DELETED: 'Удаление связи с CRM',
   ACCOMPLICES: 'Соисполнители', RESPONSIBLE_ID: 'Ответственный', CREATED_BY: 'Постановщик',
   TITLE: 'Изменение названия', PRIORITY: 'Приоритет задачи', GROUP_ID: 'Группа задачи',
   ARCHIVE_SNAPSHOT: 'Снимок комментария сохранён', ARCHIVE_NOT_RETURNED: 'Комментарий не вернулся из API', ARCHIVE_RETURNED: 'Комментарий снова доступен'
 };
 const tz='Europe/Moscow';
 const dateFmt=new Intl.DateTimeFormat('ru-RU',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:tz});
 const str = v => v==null?'':typeof v==='object'?JSON.stringify(v,null,2):String(v);
 const typeName = f => labels[String(f||'').toUpperCase()]||String(f||'Другое событие').replaceAll('_',' ');
 const isDeadline = e => /DEADLINE/i.test(String(e.field||''));
 const isPeople = f => /^(AUDITORS|ACCOMPLICES|RESPONSIBLE_ID|CREATED_BY)$/i.test(String(f||''));
 const isComment = f => /^COMMENT(_EDIT|_DEL)?$/i.test(String(f||''));
 const isTimeField = f => /^(DEADLINE|START_DATE_PLAN|END_DATE_PLAN|DATE_START|DATE_FINISH|CLOSED_DATE)$/i.test(String(f||''));
 const EMPTY = v => v===null || v===undefined || v==='';
 const unique = xs => [...new Set(xs.filter(x=>!EMPTY(x)))];
 // Convert Unix seconds/ms to dates only for explicitly date-like fields.
 // Never format arbitrary numeric IDs or status values as dates.
 function dateObject(raw) {
   if(raw instanceof Date && !Number.isNaN(raw.getTime()))return raw;
   if(typeof raw==='number' && Number.isFinite(raw)) {
     const seconds=Math.abs(raw)>=1e12?raw/1000:raw;
     return seconds>=946684800 && seconds<=4102444800 ? new Date(seconds*1000) : null;
   }
   if(typeof raw!=='string')return null;
   const v=raw.trim();
   if(/^\d{10}(?:\.\d+)?$/.test(v) || /^\d{13}$/.test(v))return dateObject(Number(v));
   if(!/^\d{4}-\d\d-\d\d(?:[T ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:?\d\d)?)?$/.test(v))return null;
   // Unzoned values in Bitrix logs are Moscow-local, not the browser's timezone.
   const normalized=v.replace(' ','T');
   const hasClock=normalized.includes('T');
   const withOffset=/Z$|[+-]\d\d:?\d\d$/.test(normalized)?normalized:
     `${normalized}${hasClock?(normalized.length===16?':00':''):'+00:00'}${hasClock?'':''}`;
   // If no offset was provided, interpret the date/time as MSK (+03:00).
   let iso;
   if(/Z$|[+-]\d\d:?\d\d$/.test(normalized))iso=normalized;
   else if(hasClock)iso=`${normalized}${normalized.length===16?':00':''}+03:00`;
   else iso=`${normalized}T00:00:00+03:00`;
   const dt=new Date(iso);
   return Number.isNaN(dt.getTime())?null:dt;
 }
 function formatDateValue(raw, withZone=false) {
   const d=dateObject(raw);
   if(!d)return str(raw);
   return dateFmt.format(d)+(withZone?' МСК':'');
 }
 function eventDate(raw) {return EMPTY(raw)?'Дата неизвестна':formatDateValue(raw,true);}
 function eventValue(field,value) {
   if(EMPTY(value))return '';
   if(isTimeField(field))return formatDateValue(value);
   if(typeof value==='object')return JSON.stringify(value,null,2);
   return String(value);
 }
 function ids(value){
   if(Array.isArray(value))return value.map(str).filter(Boolean);
   if(EMPTY(value))return [];
   if(typeof value==='number')return [String(value)];
   if(typeof value==='string' && /^[\d\s,;]+$/.test(value))return value.split(/[\s,;]+/).filter(Boolean);
   return [];
 }
 function peopleDiff(before,after){
   const a=unique(ids(before)),b=unique(ids(after));
   if(!a.length&&!b.length)return null;
   const added=b.filter(id=>!a.includes(id)),removed=a.filter(id=>!b.includes(id));
   return {added,removed,oldList:a,newList:b};
 }
 function nameForActor(event){
   // Author names cannot be resolved without user directory; do not guess.
   const id=event?.actor_id;
   if(EMPTY(id))return 'Автор не определён';
   return `Автор: ${namedId(id)}`;
 }
 function short(s,max=360){const v=str(s);return v.length>max?v.slice(0,max)+'…':v;}
 // Bitrix legacy API returns BBCode, not HTML. Render a readable *text-only*
 // view; the exact original string remains available under "Исходный текст".
 function cleanBitrixText(value){
   if(value===null||value===undefined)return '';
   return String(value)
     .replace(/\r\n?/g,'\n')
     .replace(/\[USER=(\d+)\]([\s\S]*?)\[\/USER\]/gi,(_,id,label)=>label.trim()||`Пользователь ID ${id}`)
     .replace(/\[URL(?:=[^\]]+)?\]([\s\S]*?)\[\/URL\]/gi,(_,label)=>label)
     .replace(/\[IMG\]([\s\S]*?)\[\/IMG\]/gi,(_,url)=>`Изображение: ${url}`)
     .replace(/\[(?:ATTACH|FILE)(?:=[^\]]+)?\]/gi,'[Вложение]')
     .replace(/\[\/?P(?:=[^\]]+)?\]/gi,'\n')
     .replace(/\[BR\s*\/?\]|\[HR\s*\/?\]/gi,'\n')
     .replace(/\[\*\]/g,'\n• ')
     .replace(/\[\/?(?:B|I|U|S|QUOTE|CODE|FONT|SIZE|COLOR|LEFT|RIGHT|CENTER|LIST|INDENT|TABLE|TR|TD|TH|SUB|SUP)(?:=[^\]]+)?\]/gi,'')
     .replace(/&(?:nbsp|amp|lt|gt|quot|apos|#39);/gi,entity=>{
       const entities={'&nbsp;':' ','&amp;':'&','&lt;':'<','&gt;':'>','&quot;':'"','&apos;':"'",'&#39;':"'"};
       return entities[entity.toLowerCase()]??entity;
     })
     .replace(/&#(?:x([0-9a-f]+)|(\d+));/gi,(full,hex,dec)=>{
       const code=Number.parseInt(hex||dec,hex?16:10);
       return code>31&&code<=0x10ffff&&!(code>=0xd800&&code<=0xdfff)?String.fromCodePoint(code):full;
     })
     .replace(/[\t ]*\n[\t ]*/g,'\n')
     .replace(/\n{3,}/g,'\n\n')
     .trim();
 }
 function previewData(e){
   const d=e.details;
   if(!d||typeof d!=='object')return typeof d==='string'?d:'';
   const v=d.text_preview??d.text??d.message??d.title??'';
   return typeof v==='string'?v:'';
 }
 // Node tests consume only these pure helpers, without requiring a browser.
 if(typeof module==='object' && module.exports){module.exports={dateObject,formatDateValue,eventDate,eventValue,peopleDiff,ids,typeName,isTimeField,cleanBitrixText,mergedTimelineEntries};return;}
 const el=id=>document.getElementById(id);
 const node=(tag,cls,content)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(content!==undefined)e.textContent=content;return e;};
 let events=[],currentTask=0,userNames={},loadedComments=[],commentByKey={},archiveItems=[],archiveEvents=[];
 function commentIdForEvent(e){
   if(!isComment(e.field))return '';
   const a=[e.new_value,e.old_value];
   return a.map(v=>String(v??'')).find(v=>/^\d+$/.test(v))||'';
 }
 function addCommentAnnotations(wrap,e){
   const id=commentIdForEvent(e);
   const comment=commentByKey['legacy:'+id];
   if(!id||!comment)return;
   if(comment.text){
     wrap.append(node('p','comment-enhanced',short(cleanBitrixText(comment.text),1800)));
     wrap.append(node('div','comment-source-inline',comment.saved?`Сохранённый снимок от ${eventDate(comment.observed_at)} · историческая редакция не подтверждена`:'Текст из API на момент запроса · историческая редакция не подтверждена'));
   }else{
     wrap.append(node('p','muted','Комментарий найден в архиве, но доступного текста нет.'));
   }
 }
 function renderComments(){
   const mount=el('comments-list');mount.replaceChildren();
   el('comments-count').textContent=`Всего: ${loadedComments.length}`;
   if(!loadedComments.length){mount.append(node('p','muted','Комментариев, доступных для чтения, не найдено.'));return;}
   loadedComments.forEach(c=>{
     const row=node('article','comment-row'),meta=node('div','comment-meta');
     meta.append(node('span','comment-source',c.source==='legacy'?'Архив комментариев':'Чат задачи'));
     meta.append(node('span','',`№${c.id}`));
     if(c.author_name||c.author_id)meta.append(node('span','',c.author_name||namedId(c.author_id)));
     if(c.created_at)meta.append(node('span','',eventDate(c.created_at)));
     row.append(meta);
     if(c.deleted)row.append(node('p','comment-notice','Сообщение отмечено как удалённое'));
     if(c.edited)row.append(node('p','comment-notice','Сообщение изменено. Показанная редакция не обязательно совпадает с исторической.'));
     const readable=cleanBitrixText(c.text);
     row.append(node('p',readable?'comment-body':'comment-body-empty',readable||'Текст недоступен в полученном ответе'));
     if(c.text&&readable!==c.text){
       const raw=document.createElement('details');raw.className='comment-raw';
       raw.append(node('summary','','Исходный текст с разметкой Bitrix24'));
       raw.append(node('pre','',c.text));row.append(raw);
     }
     // A comment ID is a reliable link only inside the legacy comment namespace.
     // Not all comments have an event in the saved history; never fabricate one.
     if(c.source==='legacy'){
       const eventIndex=events.findIndex(e=>commentIdForEvent(e)===String(c.id));
       if(eventIndex>=0){
         const jump=node('button','comment-jump','Показать событие в хронологии');
         jump.type='button';
         jump.addEventListener('click',()=>{
           for(const id of ['type-filter','actor-filter','from-filter','to-filter','search'])el(id).value='';
           renderTimeline();
           const eventEl=el(`history-event-${eventIndex}`);
           if(eventEl){eventEl.scrollIntoView({behavior:'smooth',block:'center'});eventEl.focus({preventScroll:true});}
         });
         row.append(jump);
       }
     }
     mount.append(row);
   });
 }
 function renderCommentCoverage(missingIds){
   let area=el('comments-coverage');
   if(!area){area=node('div','comment-coverage');area.id='comments-coverage';el('comments-note').after(area);}
   area.replaceChildren();
   const ids=unique(events.map(commentIdForEvent));
   const found=new Set(loadedComments.filter(c=>c.source==='legacy').map(c=>String(c.id)));
   const matches=ids.filter(id=>found.has(id));
   if(!ids.length){area.append(node('p','muted','В сохранённой истории нет ID комментариев для сопоставления.'));return;}
   area.append(node('p','muted',`Сопоставлено с журналом: ${matches.length} из ${ids.length} уникальных ID комментариев. Это не число всех когда-либо существовавших комментариев.`));
   const missing=Array.isArray(missingIds)?missingIds.map(String):ids.filter(id=>!found.has(id));
   if(missing.length){
     const details=document.createElement('details');details.className='comment-raw';
     details.append(node('summary','',`Не найдены через архивный API: ${missing.length} ID`));
     details.append(node('p','muted',`ID: ${missing.join(', ')}. Причина не установлена: запись могла быть удалена, недоступна или отсутствовать в текущей выдаче.`));
     area.append(details);
   }
 }
 function namedId(id){const key=String(id);return userNames[key]?`${userNames[key]} (ID ${key})`:`ID ${key}`;}
 function setMsg(v,bad=false){el('message').textContent=v;el('message').classList.toggle('error',bad);}
 function rebuildFilters(){
   const entries=[
     ['type-filter',unique(mergedTimelineEntries(events,archiveEvents).map(e=>e.field)).sort(),v=>typeName(v)],
     ['actor-filter',unique(mergedTimelineEntries(events,archiveEvents).map(e=>e.actor_id)).sort((a,b)=>Number(a)-Number(b)),v=>namedId(v)]
   ];
   for(const [id,vals,display] of entries){
     const select=el(id),saved=select.value;
     while(select.options.length>1)select.remove(1);
     vals.forEach(v=>{const o=document.createElement('option');o.value=String(v);o.textContent=display(v);select.append(o)});
     if([...select.options].some(o=>o.value===saved))select.value=saved;
   }
 }
 function changeContents(e){
   const wrap=node('div','change-content');
   if(e.archive_kind){
     wrap.append(node('div','change-summary',`Комментарий №${e.comment_id} · ${e.comment_source==='legacy'?'прежняя карточка':'чат задачи'}`));
     if(e.archive_kind==='snapshot'){
       wrap.append(node('p','comment-enhanced',short(cleanBitrixText(e.archive_text),1800)||'В снимке текст отсутствует'));
       wrap.append(node('p','comment-source-inline',`Версия ${e.archive_version}. Фиксация при чтении API; это не исходная редакция на дату создания.`));
     }else if(e.archive_kind==='not_returned'){
       wrap.append(node('p','comment-notice','Ранее архивированный комментарий не вернулся при полном чтении источника. Это не доказательство его удаления.'));
     }else{
       wrap.append(node('p','comment-source-inline','Комментарий повторно появился в ответе API.'));
     }
     return wrap;
   }
   const old=e.old_value, next=e.new_value,field=String(e.field||'').toUpperCase();
   if(isPeople(field)){
     const change=peopleDiff(old,next);
     if(change){
       if(change.added.length)wrap.append(node('p','change-summary',`Добавлены: ${change.added.map(namedId).join(', ')}`));
       if(change.removed.length)wrap.append(node('p','change-summary',`Удалены: ${change.removed.map(namedId).join(', ')}`));
       if(!change.added.length&&!change.removed.length)wrap.append(node('p','change-summary','Состав участников без изменений'));
       if(change.oldList.length||change.newList.length){
         const details=node('div','change-secondary',`Было: ${change.oldList.map(namedId).join(', ')||'не указано'} · Стало: ${change.newList.map(namedId).join(', ')||'не указано'}`);
         wrap.append(details);
       }
       return wrap;
     }
   }
   if(isComment(field)){
     const id=(!EMPTY(next)&&/^\d+$/.test(str(next)))?String(next):(!EMPTY(old)&&/^\d+$/.test(str(old)))?String(old):'';
     const content=previewData(e);
     if(id)wrap.append(node('div','change-summary',`Комментарий №${id}`));
     if(!EMPTY(old)&&!EMPTY(next)&&old!==next && !id){renderPair(wrap,field,old,next);}
     if(content)wrap.append(node('p','event-preview',short(cleanBitrixText(content))));
     else if(id&&commentByKey['legacy:'+id])addCommentAnnotations(wrap,e);
     if(!content && id && !commentByKey['legacy:'+id])wrap.append(node('p','muted','Текст комментария отсутствует в сохранённом событии. Попробуйте прочитать архив.'));
     if(wrap.childNodes.length)return wrap;
   }
   if(!EMPTY(old)||!EMPTY(next)){renderPair(wrap,field,old,next);return wrap;}
   const preview=previewData(e);
   if(preview)wrap.append(node('p','event-preview',short(preview)));
   else if(typeof e.details==='string'&&e.details)wrap.append(node('p','event-preview',short(e.details)));
   else wrap.append(node('p','muted','Подробности доступны в исходной записи ниже.'));
   return wrap;
 }
 function renderPair(mount,field,old,next){
   const pair=node('div','value-pair');
   if(!EMPTY(old))pair.append(node('span','old-value',eventValue(field,old)));
   if(!EMPTY(old)&&!EMPTY(next))pair.append(node('span','change-arrow','→'));
   if(!EMPTY(next))pair.append(node('span','new-value',eventValue(field,next)));
   mount.append(pair);
 }
 function renderDeadlines(){
   const mount=el('deadlines');mount.replaceChildren();
   const rows=events.filter(isDeadline).slice().reverse();
   el('deadline-count').textContent=`${rows.length} событий`;
   if(!rows.length){mount.append(node('p','muted','Переносы срока среди загруженных событий не найдены.'));return;}
   rows.forEach(e=>{const item=node('div','deadline-entry');item.append(node('div','deadline-date',eventDate(e.occurred_at)));item.append(changeContents(e));item.append(node('div','muted',nameForActor(e)));mount.append(item)});
 }
 function mergedTimelineEntries(history, snapshots){
   // Do not duplicate the first captured version if a historical COMMENT event
   // already points to that legacy comment. The source event's date remains
   // its real timestamp; the captured text is an annotation with observed_at.
   const linked = new Set(history.filter(e=>isComment(e.field)).map(e=>{
     for(const val of [e.new_value,e.old_value]){
       const id=String(val??'');
       if(/^\d+$/.test(id))return id;
     }
     return '';
   }).filter(Boolean));
   return [...history, ...snapshots.filter(e=>!(
     e.archive_kind==='snapshot' && e.comment_source==='legacy' &&
     Number(e.archive_version)===1 && linked.has(String(e.comment_id))
   ))];
 }
 function renderTimeline(){
   const kind=el('type-filter').value,actor=el('actor-filter').value;
   const from=el('from-filter').value,to=el('to-filter').value,keyword=el('search').value.toLocaleLowerCase('ru-RU').trim();
   const all=mergedTimelineEntries(events,archiveEvents).sort((a,b)=>
     (dateObject(b.occurred_at)?.getTime()||0)-(dateObject(a.occurred_at)?.getTime()||0));
   const items=all.filter(e=>{
     if(kind&&String(e.field)!==kind)return false;
     if(actor&&String(e.actor_id)!==actor)return false;
     const day=(e.occurred_at||'').slice(0,10);
     if(from&&day&&day<from)return false;
     if(to&&day&&day>to)return false;
     if(keyword&&!`${typeName(e.field)} ${str(e.old_value)} ${str(e.new_value)} ${str(e.details)} ${str(e.archive_text)} ${eventValue(e.field,e.old_value)} ${eventValue(e.field,e.new_value)} ${e.actor_id} ${userNames[String(e.actor_id)]||''}`.toLocaleLowerCase('ru-RU').includes(keyword))return false;
     return true;
   });
   if(el('sort').value==='asc')items.reverse();
   const linkedCount=events.length+archiveEvents.length-all.length;
   el('visible-count').textContent=`Показано: ${items.length} · событий задачи: ${events.length} · отдельных записей архива: ${archiveEvents.length-linkedCount} · снимков, связанных с событиями: ${linkedCount}`;
   const mount=el('timeline');mount.replaceChildren();
   if(!items.length){mount.append(node('p','muted','По выбранным фильтрам событий нет.'));return;}
   items.forEach(e=>{
     const item=node('article','event');const head=node('div','event-heading');
     head.append(node('span','event-label'+(isDeadline(e)?' priority':''),typeName(e.field)));
     head.append(node('span','event-time',eventDate(e.occurred_at)));
     item.id=e.archive_kind?`archive-event-${e.archive_id}-${e.archive_kind}`:`history-event-${events.indexOf(e)}`;item.tabIndex=-1;
     item.append(head);
     item.append(node('div','event-actor',nameForActor(e)));
     item.append(changeContents(e));
     const details=document.createElement('details');details.append(node('summary','','Исходные данные события'));
     details.append(node('pre','payload',JSON.stringify(e.details,null,2)??'Данных нет'));
     item.append(details);mount.append(item);
   });
 }
 async function api(url,method='GET'){
   const response=await fetch(url,{method,headers:{Authorization:'Bearer '+el('token').value.trim()},cache:'no-store'});
   const ct=response.headers.get('content-type')||'';
   const data=ct.includes('application/json')?await response.json():{};
   if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:`Ошибка HTTP ${response.status}`);
   return data;
 }
 function prepareArchiveEvents(data){
   const authors=new Map((data.items||[]).map(x=>[`${x.source}:${x.comment_id}`,x.author_id]));
   return (data.archive_events||[]).map(x=>({
     archive_kind:x.kind, archive_id:x.id, field:x.kind==='snapshot'?'ARCHIVE_SNAPSHOT':
       x.kind==='not_returned'?'ARCHIVE_NOT_RETURNED':'ARCHIVE_RETURNED',
     occurred_at:x.observed_at, actor_id:authors.get(`${x.source}:${x.comment_id}`)||'',
     archive_text:x.text||'', archive_version:x.version_no||0,
     comment_id:x.comment_id, comment_source:x.source,
     details:{source:x.source,comment_id:x.comment_id,version:x.version_no||null,
              observed_at:x.observed_at,note:x.note||'Снимок получен из Битрикс24'}
   }));
 }
 function renderSavedArchive(data){
   const mount=el('archive-list');mount.replaceChildren();
   const stats=data.stats||{};
   el('archive-count').textContent=data.initialized?
     `Сохранено: ${stats.comments||0} комментариев · ${stats.versions||0} версий`:'Архив ещё пуст';
   if(!data.initialized){el('archive-note').textContent='Тестовая база снимков ещё не создана. Создаётся только при нажатии кнопки сохранения.';return;}
   const latestChecks=(data.checks||[]).slice(0,2).map(x=>`${x.source==='legacy'?'Архив':'Чат'}: ${x.result==='complete'?'полный ответ':x.result==='unavailable'?'недоступен':'частичный ответ'}`);
   el('archive-note').textContent=`Тексты хранятся отдельно от истории поручений. Последние проверки – ${latestChecks.join(', ')||'нет'}. Отсутствие в API не означает удаление.`;
   for(const c of (data.items||[])){
     const row=node('article','comment-row saved-comment');
     const header=node('div','comment-meta');
     header.append(node('span','comment-source',c.source==='legacy'?'Старый архив':'Чат'));
     header.append(node('span','',`№${c.comment_id}`));
     header.append(node('span','',c.author_name||`ID ${c.author_id||'—'}`));
     header.append(node('span','',`Версий: ${c.versions.length}`));
     if(c.availability==='not_returned')header.append(node('span','archive-missing','Нет в последнем полном ответе API'));
     row.append(header);
     const versions=c.versions||[];
     const current=versions[versions.length-1];
     if(current){
       row.append(node('p','comment-body',short(cleanBitrixText(current.body),750)||'Текст отсутствует в снимке'));
       row.append(node('p','comment-source-inline',`Впервые зафиксирован: ${eventDate(c.first_seen_at)} · последний ответ: ${eventDate(c.last_seen_at)}`));
       if(versions.length>1){
         const diff=document.createElement('details');diff.className='comment-raw';
         diff.append(node('summary','','Сравнить две последние зафиксированные версии'));
         const columns=node('div','version-compare');
         const previous=versions[versions.length-2],latest=versions[versions.length-1];
         for(const [label,version] of [['Было',previous],['Стало',latest]]){
           const part=node('div','version-compare-part');
           part.append(node('strong','',`${label}: версия ${version.version_no} · ${eventDate(version.observed_at)}`));
           part.append(node('p','comment-body',cleanBitrixText(version.body)||'Текст отсутствует'));
           columns.append(part);
         }
         diff.append(columns);row.append(diff);
         const details=document.createElement('details');details.className='comment-raw';
         details.append(node('summary','',`Посмотреть все ${versions.length} сохранённые редакции`));
         for(const v of versions){
           const vRow=node('div','archive-version');
           vRow.append(node('strong','',`Версия ${v.version_no} · ${eventDate(v.observed_at)}`));
           vRow.append(node('p','comment-body',cleanBitrixText(v.body)||'Текст отсутствует'));
           details.append(vRow);
         }
         row.append(details);
       }
     }
     mount.append(row);
   }
 }
 async function loadArchive(){
   const d=await api(`/controller-pilot-test/history/${currentTask}/comment-archive`);
   archiveItems=Array.isArray(d.items)?d.items:[];
   for(const c of archiveItems){
     if(c.source!=='legacy')continue;
     const key=`legacy:${c.comment_id}`;
     if(commentByKey[key])continue;
     const latest=c.versions?.[c.versions.length-1];
     if(latest)commentByKey[key]={source:'legacy',id:c.comment_id,text:latest.body,saved:true,observed_at:latest.observed_at};
   }
   archiveEvents=prepareArchiveEvents(d);
   renderSavedArchive(d);
   rebuildFilters();renderTimeline();
 }
 async function load(){
   const id=Number(el('task').value),token=el('token').value.trim();
   if(!Number.isSafeInteger(id)||id<=0){setMsg('Укажите корректный ID задачи.',true);return;}
   if(!token){setMsg('Введите токен тестового API.',true);return;}
   el('load').disabled=true;setMsg('Читаем сохранённые события…');
   try{
     // Same v6 API, still read-only, no extra requests to Bitrix24.
     const data=await api(`/controller-pilot-test/history/${id}/events?limit=1000`);
     events=Array.isArray(data.events)?data.events:[];if(id!==currentTask){userNames={};loadedComments=[];commentByKey={};archiveItems=[];archiveEvents=[];el('comments-list').replaceChildren();el('comments-count').textContent='Не загружены';const coverage=el('comments-coverage');if(coverage)coverage.replaceChildren();el('comments-note').textContent='Сохранённая хронология останется без изменений.';}currentTask=id;
     el('result').hidden=false;
     el('n-events').textContent=String(data.total);
     el('n-fields').textContent=String(unique(events.map(e=>e.field)).length);
     el('n-actors').textContent=String(unique(events.map(e=>e.actor_id)).length);
     el('n-deadlines').textContent=String(events.filter(isDeadline).length);
     rebuildFilters();renderDeadlines();renderTimeline();
     try{await loadArchive();}catch(err){el('archive-note').textContent=`Снимки пока недоступны: ${err.message}`;}
     setMsg(`Задача № ${id}: загружено ${events.length} из ${data.total} событий. ${data.has_more?'Показаны первые 1000.':''}`);
   }catch(err){setMsg(err.message||'Не удалось загрузить историю',true)}
   finally{el('load').disabled=false}
 }
 el('comments-load').addEventListener('click',async()=>{
   if(!currentTask){setMsg('Сначала загрузите историю задачи.',true);return;}
   const btn=el('comments-load');btn.disabled=true;
   el('comments-note').textContent='Читаем архив и чат задачи через два REST API…';
   try{
     const d=await api(`/controller-pilot-test/history/${currentTask}/comments`);
     loadedComments=Array.isArray(d.comments)?d.comments:[];
     commentByKey=Object.fromEntries(loadedComments.map(c=>[String(c.source)+':'+String(c.id),c]));
     renderComments();renderTimeline();renderCommentCoverage(d.missing_legacy_ids);
     const count=d.counts||{};
     const extra=d.warnings?.length?' Не все источники доступны: '+d.warnings.join('; '):'';
     el('comments-note').textContent=`Архив: ${count.legacy??0}, чат: ${count.chat??0}.${extra}${d.partial?' Данные могут быть неполными.':''} Это только чтение; для фиксации нажмите «Сохранить снимки».`;
     // Full task history in SQLite is deliberately unaffected.
   }catch(err){el('comments-note').textContent='Не удалось прочитать комментарии: '+(err.message||String(err));}
   finally{btn.disabled=false;}
 });
 el('comments-save').addEventListener('click',async()=>{
   if(!currentTask){setMsg('Сначала загрузите историю задачи.',true);return;}
   const btn=el('comments-save');btn.disabled=true;
   el('archive-note').textContent='Сверяем оба источника и записываем только новые подтверждённые снимки…';
   try{
     const d=await api(`/controller-pilot-test/history/${currentTask}/comments/snapshot`,'POST');
     const f=d.fetched||{};
     loadedComments=Array.isArray(f.comments)?f.comments:[];
     commentByKey=Object.fromEntries(loadedComments.map(c=>[`${c.source}:${c.id}`,c]));
     renderComments();renderCommentCoverage(f.missing_legacy_ids);
     await loadArchive();
     const r=d.saved||{};
     el('comments-note').textContent=`Снимок записан. Новых комментариев: ${r.new_comments||0}; новых редакций: ${r.new_versions||0}; без изменений: ${r.unchanged||0}.`;
     if((r.now_not_returned||0)>0)el('archive-note').textContent+=` Ранее доступных, но не вернувшихся при полном ответе: ${r.now_not_returned}.`;
   }catch(err){el('archive-note').textContent='Сохранение не выполнено: '+(err.message||String(err));}
   finally{btn.disabled=false;}
 });
 for(const id of ['type-filter','actor-filter','from-filter','to-filter','search','sort'])el(id).addEventListener('input',renderTimeline);
 const peopleBtn=node('button','btn-primary','Получить ФИО из Битрикс24');
 peopleBtn.type='button';peopleBtn.id='people-lookup';peopleBtn.style.marginLeft='8px';
 peopleBtn.style.background='#426a87';peopleBtn.style.minHeight='34px';
 el('message').parentElement.append(peopleBtn);
 peopleBtn.addEventListener('click',async()=>{
   if(!currentTask){setMsg('Сначала загрузите историю задачи.',true);return;}
   peopleBtn.disabled=true;
   setMsg('Запрашиваем ФИО только участников сохранённой истории…');
   try{
     const res=await api(`/controller-pilot-test/history/${currentTask}/people`);
     userNames=res.names&&typeof res.names==='object'?res.names:{};
     rebuildFilters();renderDeadlines();renderTimeline();
     setMsg(`ФИО: найдено ${res.resolved} из ${res.requested}. Остальные пользователи отображаются по ID.`);
   }catch(err){setMsg(`ФИО недоступны: ${err.message}. История сохранена.`,true)}
   finally{peopleBtn.disabled=false;}
 });
 // A link from the overview carries only the task ID. Never place a token in a URL.
 const requestedTask=new URLSearchParams(location.search).get('task_id');
 if(requestedTask && /^\d{1,10}$/.test(requestedTask) && Number(requestedTask)>0)el('task').value=requestedTask;
 el('load').addEventListener('click',load);
 el('task').addEventListener('keydown',e=>{if(e.key==='Enter')load()});
 el('token').addEventListener('keydown',e=>{if(e.key==='Enter')load()});
 el('diagnostics').addEventListener('click',async e=>{
   e.preventDefault();if(!currentTask)return;
   const pre=el('diagnostics-output');if(!pre.hidden){pre.hidden=true;return;}
   try{const d=await api(`/controller-pilot-test/history/${currentTask}/diagnostics`);pre.textContent=JSON.stringify(d,null,2);pre.hidden=false;}
   catch(err){setMsg(err.message,true)}
 });
})();
