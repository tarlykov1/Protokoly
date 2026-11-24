'use strict';
const Model = (() => {
  const missing='Нет данных';
  const day=v=>v && new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Moscow'}).format(new Date(v));
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
  function metrics(rows,complete){
    if(!complete)return [null,null,null];
    const done=rows.filter(r=>r.state==='done');
    const unknown=rows.some(r=>r.state==null);
    return [discipline(rows.map(r=>r.state)),unknown||done.some(r=>!r.due||!r.closed)?null:
      ratio(done.filter(r=>Date.parse(r.closed)<=Date.parse(r.due)).length,done.length),
      unknown?null:rows.filter(r=>r.state==='obsolete').length];
  }
  const zones={
    'Просрочено':(r,now)=>r.state==='open'?(r.due?Date.parse(r.due)<now:false):r.state==null?null:false,
    'Ждёт контроля':r=>r.status==='4','Срок сегодня':(r,now)=>r.state==='open'&&day(r.due)===day(now),
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
  return {bucket,missing,day,match,metrics,zones,series,discipline};
})();
if(typeof module!=='undefined') module.exports=Model;
