// Live navigation and saved mission results. No gameplay submissions or extra polling.
function operationCountdown(timers,elapsed,running=true){
 const values=Object.values(timers||{});if(!values.length)return null;
 return {count:values.length,seconds:Math.max(0,Math.ceil(Math.min(...values)-(running?elapsed:0)))};
}
function countdownLabel(seconds){
 if(seconds<=0)return 'Resolving…';
 const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60;
 return h?h+'h '+String(m).padStart(2,'0')+'m':m+':'+String(s).padStart(2,'0');
}
if(typeof module!=='undefined')module.exports={operationCountdown,countdownLabel};
if(typeof document!=='undefined')(()=>{
 const dock=document.querySelector('.player-menu'),seed=document.getElementById('military-portal-data'),resultsSeed=document.getElementById('operation-results-data');
 if(!dock||!seed||!resultsSeed)return;
 const link=document.createElement('a');link.href='#conflict';link.className='operations-shortcut';link.hidden=true;
 const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');
 const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M4 3l16 17M3 7l4-4M16 17l4-4M20 3L4 20M17 3l4 4M3 16l4 4');icon.append(path);
 const label=document.createElement('span'),timer=document.createElement('small');link.append(icon,label,timer);dock.append(link);
 let military={},received=performance.now();
 function tick(){
  const status=operationCountdown(military.raid_timers,(performance.now()-received)/1000,military.clock_running!==false),before=link.hidden;
  link.hidden=!status;if(before!==link.hidden)requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));if(!status)return;
  label.textContent='Operations · '+status.count;timer.textContent=countdownLabel(status.seconds);
  const title=status.count+' active raid(s) involving your settlement. Next resolution: '+timer.textContent+'. Open military operations and battle reports.';
  link.title=title;link.setAttribute('aria-label',title);
 }
 function updateMilitary(state){military=state||{};received=performance.now();tick();}
 window.addEventListener('military-portal',event=>updateMilitary(event.detail));
 try{updateMilitary(JSON.parse(seed.dataset.dashboard));}catch(_){}
 const interval=setInterval(tick,1000);window.addEventListener('pagehide',()=>clearInterval(interval));
 const panel=document.createElement('details');panel.className='operation-results';
 const heading=document.createElement('summary');heading.textContent='Results';const list=document.createElement('div');panel.append(heading,list);document.body.append(panel);
 const toast=document.createElement('div');toast.className='operation-toast';toast.hidden=true;toast.setAttribute('role','status');
 const message=document.createElement('span'),view=document.createElement('button'),dismiss=document.createElement('button');view.type=dismiss.type='button';view.textContent='View results';dismiss.textContent='×';dismiss.setAttribute('aria-label','Dismiss result notification');toast.append(message,view,dismiss);document.body.append(toast);
 let entries=[],seen=new Set(),key=null,signature=null;
 function remember(){for(const item of entries)seen.add(item.id);try{localStorage.setItem(key,JSON.stringify([...seen].slice(-100)));}catch(_){}refreshCount();toast.hidden=true;}
 function refreshCount(){const count=entries.filter(item=>!seen.has(item.id)).length;heading.textContent=count?'Results · '+count+' new':'Results';}
 panel.addEventListener('toggle',()=>{if(panel.open)remember();});view.addEventListener('click',()=>{panel.open=true;remember();});dismiss.addEventListener('click',()=>{toast.hidden=true;});
 function updateResults(data){
  const nextKey='operation-results-seen:'+data.settlement_id;
  if(key!==nextKey){key=nextKey;try{seen=new Set(JSON.parse(localStorage.getItem(key)||'[]'));}catch(_){seen=new Set();}signature=null;}
  const next=JSON.stringify(data.results||[]);if(next===signature)return;signature=next;entries=data.results||[];
  const fresh=entries.filter(item=>!seen.has(item.id));list.replaceChildren();
  if(!entries.length){const empty=document.createElement('p');empty.textContent='Completed raids and expeditions will appear here.';list.append(empty);}
  for(const item of entries){
   const card=document.createElement('article'),title=document.createElement('strong'),text=document.createElement('p'),date=document.createElement('small'),open=document.createElement('a');
   title.textContent=item.title;text.textContent=item.text;date.textContent=new Date(item.at*1000).toLocaleString();open.href=item.href;open.textContent='Open full report';open.addEventListener('click',()=>{panel.open=false;toast.hidden=true;});card.append(title,date,text,open);list.append(card);
  }
  if(panel.open)remember();else{
   refreshCount();if(fresh.length){message.textContent=fresh.length===1?fresh[0].title+'. '+fresh[0].text.slice(0,170):fresh.length+' mission results are available.';toast.hidden=false;}
  }
 }
 window.addEventListener('operation-results',event=>updateResults(event.detail));
 try{updateResults(JSON.parse(resultsSeed.dataset.results));}catch(_){}
})();
