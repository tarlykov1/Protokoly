// v3.15 – mutual facet filtering for the controller dashboard.
// In the deployment ZIP these helpers are integrated into dashboard.js
// before render(), replacing the global one-time options(...) loading.
const FACETS=['type','group','event','assignee'];
const FACET_LABELS={type:'Все документы',group:'Все группы',event:'Все мероприятия',assignee:'Все исполнители'};
const FACET_TEXT={type:x=>x.type,group:x=>x.group,event:x=>x.event};
const personNames=x=>[x.responsible,...(Array.isArray(x.accomplices)?x.accomplices:[])].filter(Boolean);
function facetMatches(x,id,value){
 if(!value)return true;
 if(id==='assignee')return personNames(x).includes(value);
 if(id==='period')return value==='all'||status(x)===value||(value==='active'&&['active','late','soon'].includes(status(x)));
 if(id==='search')return [x.title,x.document,x.responsible,x.group,x.event,...personNames(x)].join(' ').toLocaleLowerCase('ru').includes(value.toLocaleLowerCase('ru'));
 return String(x[id]??'')===value;
}
function currentFilters(){return {
 type:$('type').value,group:$('group').value,event:$('event').value,assignee:$('assignee').value,
 period:$('period').value,search:$('search').value.trim()
};}
function matchFilters(x,filters,excluded=''){
 return Object.entries(filters).every(([id,value])=>id===excluded||facetMatches(x,id,value));
}
function getFacetValues(items,id){
 const values=id==='assignee'?items.flatMap(personNames):items.map(FACET_TEXT[id]);
 return [...new Set(values.filter(x=>typeof x==='string'&&x.trim()))].sort((a,b)=>a.localeCompare(b,'ru'));
}
function rebuildFacet(id,values){
 const select=$(id),current=select.value;
 const fragment=document.createDocumentFragment();
 const add=(value,label)=>{const el=document.createElement('option');el.value=value;el.textContent=label;fragment.append(el)};
 add('',FACET_LABELS[id]);values.forEach(v=>add(v,v));
 select.replaceChildren(fragment);
 if(current && values.includes(current)) select.value=current;
 else if(current) select.value='';
 return current!==select.value;
}
function syncAssigneeUI(){
 const input=$('assigneeSearch'),select=$('assignee');
 if(!input)return;
 if(document.activeElement!==input || select.value){input.value=select.value;}
 select.dispatchEvent(new Event('optionsupdated'));
}
function updateFacets(){
 const selected=currentFilters();
 let assigneeChanged=false;
 for(const id of FACETS){
  const matching=data.filter(x=>matchFilters(x,selected,id));
  const values=getFacetValues(matching,id);
  if(rebuildFacet(id,values) && id==='assignee')assigneeChanged=true;
 }
 if(assigneeChanged || document.activeElement!==$('assigneeSearch'))syncAssigneeUI();
}
function reconcileFacetChange(changed){
 if(!FACETS.includes(changed)&&changed!=='period')return;
 const initial=currentFilters();
 const checkedOrder=[changed,...FACETS.filter(id=>id!==changed)];
 const retained={};
 for(const id of checkedOrder){
   const value=initial[id];if(!value)continue;
   if(data.some(x=>matchFilters(x,{...retained,[id]:value}))){retained[id]=value;}
   else if(id!==changed){$(id).value='';}
 }
}

// Wiring in dashboard.js:
// render(changed='') starts with reconcileFacetChange(changed);updateFacets();
// visible = data.filter(x=>matchFilters(x,currentFilters()));
// On each change: ()=>render(id)
// loadApi sets data, then calls render() (do NOT call global options()).
// assignee select handles 'optionsupdated' to update the searchable input.
