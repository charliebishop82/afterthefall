function xpProgress(level,xp,thresholds){
 const maximum=level>=thresholds.length,lower=thresholds[Math.min(level-1,thresholds.length-1)],upper=maximum?lower:thresholds[level];
 const span=Math.max(1,upper-lower);return {maximum,remaining:Math.max(0,upper-xp),target:upper,span,earned:maximum?span:Math.max(0,Math.min(span,xp-lower))};
}
if(typeof module!=='undefined')module.exports={xpProgress};
if(typeof document!=='undefined')(()=>{
 const panel=document.getElementById('citizen-progression');if(!panel)return;
 let thresholds;try{thresholds=JSON.parse(panel.dataset.xpThresholds);}catch(_){return;}
 window.addEventListener('citizen-portal',event=>{
  for(const citizen of event.detail||[]){
   const row=panel.querySelector('[data-xp-citizen="'+citizen.id+'"]');if(!row)continue;
   const p=xpProgress(citizen.level,citizen.xp,thresholds);
   row.querySelector('[data-xp-level]').textContent=citizen.level;
   row.querySelector('[data-xp-total]').textContent=citizen.xp.toFixed(2);
   row.querySelector('[data-xp-next]').textContent=p.maximum?'Maximum level':p.remaining.toFixed(2)+' XP to level '+(citizen.level+1)+' ('+p.target+' total)';
   const bar=row.querySelector('[data-xp-bar]');bar.max=p.span;bar.value=p.earned;
  }
 });
})();
