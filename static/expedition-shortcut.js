// Navigation only: reuse the existing military snapshot and expedition controls.
function expeditionSummary(trips){
 const active=(trips||[]).filter(trip=>trip.status!=='returned');
 if(!active.length)return null;
 const citizens=active.reduce((sum,trip)=>sum+(trip.crew||[]).length,0);
 const seconds=Math.min(...active.map(trip=>Math.max(0,Number(trip.seconds)||0)));
 return {citizens,trips:active.length,minutes:Math.ceil(seconds/60),returning:active.every(trip=>trip.status==='returning'),names:active.flatMap(trip=>trip.crew||[])};
}
if(typeof module!=='undefined')module.exports={expeditionSummary};
if(typeof document!=='undefined')(()=>{
 const dock=document.querySelector('.player-menu'),seed=document.getElementById('military-portal-data');if(!dock||!seed)return;
 const link=document.createElement('a');link.href='#expeditions';link.className='expedition-shortcut';link.hidden=true;
 const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');
 const shape=document.createElementNS('http://www.w3.org/2000/svg','path');shape.setAttribute('d','M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM16 8l-3 5-5 3 3-5Z');icon.append(shape);
 const label=document.createElement('span'),eta=document.createElement('small');link.append(icon,label,eta);dock.append(link);
 function update(state){
  const summary=expeditionSummary(state?.expeditions),wasHidden=link.hidden;link.hidden=!summary;
  if(wasHidden!==link.hidden)requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));
  if(!summary)return;
  label.textContent=(summary.returning?'Returning':'Exploring')+' · '+summary.citizens;
  eta.textContent='Next return '+summary.minutes+'m';
  const title=summary.citizens+' citizen(s) away on '+summary.trips+' expedition(s). Next scheduled return in '+summary.minutes+' minutes. Open expedition details and early recall controls. '+summary.names.join(', ');
  link.title=title;link.setAttribute('aria-label',title);
 }
 window.addEventListener('military-portal',event=>update(event.detail));
 try{update(JSON.parse(seed.dataset.dashboard));}catch(_){}
})();
