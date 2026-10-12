function matchesMapFilter(flags,filter) {
  return filter==='all' || ['unstaffed','stalled','damaged'].includes(filter) && Boolean(flags[filter]);
}
if (typeof module !== 'undefined') module.exports={matchesMapFilter};
if (typeof document !== 'undefined') (()=>{
  const map=document.querySelector('.map-scroll svg');if (!map) return;
  const panel=map.closest('.map-panel');
  const controls=document.createElement('div');controls.className='map-filters';
  const label=document.createElement('label');label.textContent='Highlight ';
  const select=document.createElement('select');select.setAttribute('aria-label','Map attention filter');
  for (const [key,text] of [['all','All structures'],['unstaffed','Unstaffed'],['stalled','Stalled work'],['damaged','Damaged']]) {
    const option=document.createElement('option');option.value=key;option.textContent=text;select.append(option);
  }
  const count=document.createElement('span');count.setAttribute('role','status');label.append(select);controls.append(label,count);
  panel.querySelector('.map-scroll').before(controls);
  const key='map-filter:'+document.title;
  try {const saved=sessionStorage.getItem(key);if ([...select.options].some(o=>o.value===saved)) select.value=saved;} catch (_) {}
  function refresh() {
    let matches=0,total=0;
    for (const node of map.querySelectorAll('[data-map-key]')) {
      const flags=Object.fromEntries(['unstaffed','stalled','damaged'].map(k=>[k,node.getAttribute('data-'+k)==='1']));
      const match=matchesMapFilter(flags,select.value);total++;if (match) matches++;
      node.classList.toggle('map-filter-dim',!match);node.classList.toggle('map-filter-match',select.value!=='all' && match);
    }
    count.textContent=select.value==='all' ? total+' structures' : matches+' matching · others remain visible';
    try {sessionStorage.setItem(key,select.value);} catch (_) {}
  }
  select.addEventListener('change',refresh);
  window.addEventListener('map-filter-state',event=>{
    for (const node of map.querySelectorAll('[data-map-key]')) {
      const flags=event.detail[node.dataset.mapKey];if (!flags) continue;
      for (const key of ['unstaffed','stalled','damaged']) node.setAttribute('data-'+key,flags[key] ? '1' : '0');
    }
    refresh();
  });
  refresh();
})();
