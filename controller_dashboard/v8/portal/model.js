'use strict';
const Model = (() => {
  const missing='Нет данных';
  const dateFormat=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Moscow'});
  const day=v=>v && dateFormat.format(new Date(v));
  const includes=(a,b)=>String(a??'').toLocaleLowerCase('ru').includes(b.toLocaleLowerCase('ru'));
  function match(r,f){
    const between=(value,from,to)=>(!from&&!to)||(value&&(!from||value>=from)&&(!to||value<=to));
    return (!f.source||r.source===f.source)&&(!f.group||String(r.group)===f.group)&&includes(r.event,f.event)
      &&includes([r.responsible,...(r.accomplices||[])].join(' '),f.person)&&includes([r.id,r.title,r.document].join(' '),f.query)
      &&between(day(r.assigned),f.from,f.until)&&between(day(r.due),f.dueFrom,f.dueTo);
  }
  function ratio(n,d){return d ? Math.round(n*1000/d)/10 : null;}
  function discipline(states){
    if(states.some(s=>!['open','done','obsolete'].includes(s))) return null;
    return ratio(states.filter(s=>s==='done').length,states.filter(s=>s!=='obsolete').length);
  }
  function tally(rows,test){
    let yes=0, unknown=0;
    for(const row of rows){
      const result=test(row);
      if(result==null) unknown++;
      else if(result) yes++;
    }
    return {yes,unknown,total:rows.length};
  }
  function kpiCoverage(rows){
    const execution=tally(rows,r=>r.state==null?null:r.state==='done');
    const known=rows.filter(r=>r.state==='open'||r.state==='done');
    const closed=rows.filter(r=>r.state==='done');
    const timely=tally(closed,r=>{
      const due=Date.parse(r.due),at=Date.parse(r.closed);
      return Number.isFinite(due)&&Number.isFinite(at)?at<=due:null;
    });
    return {execution,timely,active:known.length,discipline:ratio(execution.yes,known.length),
      onTime:ratio(timely.yes,timely.total-timely.unknown)};
  }
  function metrics(rows,complete){
    if(!complete)return [null,null,null];
    const done=rows.filter(r=>r.state==='done');
    const unknown=rows.some(r=>r.state==null);
    return [discipline(rows.map(r=>r.state)),unknown||done.some(r=>!r.due||!r.closed)?null:
      ratio(done.filter(r=>Date.parse(r.closed)<=Date.parse(r.due)).length,done.length),
      unknown?null:rows.filter(r=>r.state==='obsolete').length];
  }
  // Missing status or date leaves the answer unknown. Closed tasks carry no current risk.
  function openDeadline(row,predicate){
    if(row.state==null)return null;
    if(row.state!=='open')return false;
    const due=Date.parse(row.due);
    return Number.isFinite(due)?predicate(due):null;
  }
  function exactCount(rows,predicate){
    let count=0;
    for(const row of rows){
      const value=predicate(row);
      if(value==null)return null;
      if(value)count++;
    }
    return count;
  }
  // Compare Moscow calendar days separately from the precise time of the deadline.
  const intervalDays=(start,end)=>(Date.parse(day(end))-Date.parse(day(start)))/86400000;
  const upcoming=(r,now,days)=>openDeadline(r,due=>due>=now&&intervalDays(now,due)<=days);
  const overdueWeek=(r,now)=>openDeadline(r,due=>intervalDays(due,now)>7);
  function stageDeadlines(rows,now){
    if(rows.every(r=>r.state==='done')){
      const closedByDue=r=>{
        const due=Date.parse(r.due),closed=Date.parse(r.closed);
        return Number.isFinite(due)&&Number.isFinite(closed)?closed<=due:null;
      };
      const onTime=exactCount(rows,closedByDue);
      return [['Закрыто с просрочкой',onTime==null?null:rows.length-onTime],['Закрыто в срок',onTime]];
    }
    return [
      ['Срок истёк',exactCount(rows,r=>openDeadline(r,due=>due<now))],
      ['Срок не истёк',exactCount(rows,r=>openDeadline(r,due=>due>=now))],
    ];
  }
  function groupRows(rows,key){
    const by=new Map();
    for(const row of rows){
      const label=key(row);
      if(!by.has(label))by.set(label,[]);
      by.get(label).push(row);
    }
    return by;
  }
  const zones={
    'Просрочено':(r,now)=>openDeadline(r,due=>due<now),
    'Ждёт контроля':r=>r.status==null?null:r.status==='4',
    'Срок сегодня':(r,now)=>openDeadline(r,due=>day(due)===day(now)),
    'Срок в ближайшие 5 дней':(r,now)=>upcoming(r,now,5),
    'Просрочка более 7 дней':overdueWeek,
    'Внесены изменения':r=>r.history?r.history.changes.length>0:null,
    'Без активности более 7 рабочих дней':r=>r.state==='open'?r.inactive:r.state==null?null:false,
    'Неоднократный перенос срока':r=>r.history?r.history.moves>=2:null,
    'Старт позже 48 рабочих часов':r=>r.late_start,'Есть реакция контролёра':r=>r.reaction,
    'Новый комментарий':r=>r.unread,
  };
  function bucket(day,period){
    if(period==='year') return day.slice(0,4);
    if(period==='quarter') return day.slice(0,4)+' Q'+Math.ceil(Number(day.slice(5,7))/3);
    if(period==='month') return day.slice(0,7);
    const date=new Date(day+'T12:00:00Z');
    date.setUTCDate(date.getUTCDate()-(date.getUTCDay()+6)%7);
    return date.toISOString().slice(0,10);
  }
  function series(rows,histories,groups,period){
    const byPeriod=new Map();
    const days=[...new Set(groups.flatMap(g=>Object.keys(histories[g]||{})))].sort();
    for(const day of days){
      if(groups.some(g=>!histories[g]?.[day])) continue;
      const states=rows.flatMap(r=>{
        const observation=histories[r.group][day];
        return Object.hasOwn(observation,r.id)?[observation[r.id]]:[];
      });
      byPeriod.set(bucket(day,period),discipline(states));
    }
    return [...byPeriod];
  }
  function csvCell(value){
    let text=value==null?missing:String(value);
    // Excel may evaluate task titles and names that begin with a formula marker.
    if(/^[\s]*[=+@-]|^[\t\r\n]/.test(text))text="'"+text;
    return '"'+text.replace(/"/g,'""')+'"';
  }
  function closureLabel(row){
    const closure=row.controller_closure;
    if(!closure)return '';
    return closure.accepted_submission?'Принято контролёром после сдачи':'Закрыто контролёром';
  }
  return {closureLabel,tally,kpiCoverage,stageDeadlines,csvCell,bucket,missing,day,match,metrics,zones,series,discipline,exactCount,groupRows,upcoming,overdueWeek};
})();
if(typeof module!=='undefined') module.exports=Model;
