// Draft citizen portal. Navigation only; original controls own every action.
function citizenMatches(c,filter){
  return filter==='all'||filter==='free'&&c.free||filter==='working'&&!c.free&&!c.away||
    filter==='away'&&c.away||filter==='injured'&&c.hp<c.max_hp;
}
function sortCitizens(rows,sort){
  return [...rows].sort((a,b)=>sort==='health'?a.hp/a.max_hp-b.hp/b.max_hp||a.id-b.id:
    sort==='morale'?a.morale-b.morale||a.id-b.id:sort==='level'?b.level-a.level||a.id-b.id:
    a.name.localeCompare(b.name)||a.id-b.id);
}
function citizenInitials(name){return String(name).trim().split(/\s+/).slice(0,2).map(p=>p[0]||'').join('').toUpperCase();}
if(typeof module!=='undefined')module.exports={citizenMatches,sortCitizens,citizenInitials};
if(typeof document!=='undefined')(()=>{
  const roster=document.getElementById('citizens');if(!roster)return;
  let citizens=[...roster.querySelectorAll('[data-citizen-card]')].flatMap(row=>{try{return [JSON.parse(row.dataset.citizenCard)];}catch(_){return [];}});
  const board=document.createElement('div');board.className='citizen-board';
  const heading=document.createElement('h3');heading.textContent='Citizen board';
  const intro=document.createElement('p');intro.textContent='Select a citizen to inspect them. Quick links open the existing manual assignment controls.';
  const toolbar=document.createElement('div');toolbar.className='citizen-board-toolbar';
  const filters=document.createElement('div');filters.className='citizen-filters';filters.setAttribute('aria-label','Filter citizens');
  let filter='all',selected=null;const count=document.createElement('span');count.setAttribute('role','status');
  for(const [key,label] of [['all','All'],['free','Free'],['working','Working'],['away','Away'],['injured','Injured']]){
    const button=document.createElement('button');button.type='button';button.textContent=label;button.dataset.filter=key;
    button.setAttribute('aria-pressed',String(key===filter));button.addEventListener('click',()=>{filter=key;render();});filters.append(button);
  }
  const sort=document.createElement('select');sort.setAttribute('aria-label','Sort citizens');
  for(const [key,label] of [['name','Name'],['health','Lowest health'],['morale','Lowest morale'],['level','Highest level']]){
    const option=document.createElement('option');option.value=key;option.textContent=label;sort.append(option);
  }
  sort.addEventListener('change',render);toolbar.append(filters,sort,count);
  const grid=document.createElement('div');grid.className='citizen-grid';
  const inspector=document.createElement('aside');inspector.className='citizen-inspector';inspector.hidden=true;
  inspector.setAttribute('aria-label','Selected citizen');
  const contents=document.createElement('div');const close=document.createElement('button');close.type='button';close.textContent='Close details';
  function dismiss(){const prior=selected;selected=null;inspector.hidden=true;render();grid.querySelector('[data-portal-citizen="'+prior+'"]')?.focus({preventScroll:true});}
  close.addEventListener('click',dismiss);inspector.append(contents,close);
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!inspector.hidden)dismiss();});
  board.append(heading,intro,toolbar,grid,inspector);roster.querySelector('.table-scroll').before(board);
  function node(tag,text,className){const element=document.createElement(tag);element.textContent=text;if(className)element.className=className;return element;}
  function meter(label,value,max){
    const box=document.createElement('span');box.className='citizen-meter';
    box.append(node('span',label+': '+Number(value).toFixed(1)+' / '+max));
    const bar=document.createElement('progress');bar.max=max;bar.value=Math.max(0,Math.min(max,value));bar.setAttribute('aria-label',label);box.append(bar);return box;
  }
  function detail(){
    const c=citizens.find(c=>c.id===selected);inspector.hidden=!c;if(!c)return;
    contents.replaceChildren(node('h3',c.name+' · #'+c.id),node('p','Level '+c.level+' · '+Number(c.xp).toFixed(1)+' XP'),
      meter('Health',c.hp,c.max_hp),meter('Morale',c.morale,100),node('p','Assignment: '+c.assignment));
    if(c.captured)contents.append(node('p','Captured citizen — not yet integrated.'));
    if(c.return_seconds!=null)contents.append(node('p','Expedition return: '+Math.ceil(c.return_seconds/60)+' min of active game time.'));
    const links=document.createElement('div');links.className='citizen-quick-links';
    const destinations=c.free?[['#screen-build','Work / buildings'],['#scavenging','Scavenge'],...(!c.captured?[['#expeditions','Explore the Wastes']]:[])]:[[c.target,c.target_label]];
    for(const [href,label] of destinations){const link=node('a',label);link.href=href;links.append(link);}
    contents.append(links,node('p','Use the linked controls to choose this citizen and confirm an action.','small-note'));
  }
  function render(){
    const rows=sortCitizens(citizens.filter(c=>citizenMatches(c,filter)),sort.value);
    for(const button of filters.children)button.setAttribute('aria-pressed',String(button.dataset.filter===filter));
    count.textContent=rows.length+' / '+citizens.length+' citizens';
    const focused=document.activeElement?.dataset.portalCitizen;
    const focusedLink=inspector.contains(document.activeElement)?document.activeElement.getAttribute('href'):null;
    const cards=rows.map(c=>{
      const card=document.createElement('button');card.type='button';card.className='citizen-card';card.dataset.portalCitizen=c.id;
      card.setAttribute('aria-pressed',String(c.id===selected));card.setAttribute('aria-label','Inspect '+c.name+', citizen '+c.id);
      card.append(node('span',citizenInitials(c.name),'citizen-avatar'),node('strong',c.name),node('span','#'+c.id+' · Level '+c.level,'citizen-card-level'),
        node('span',c.assignment,'citizen-state '+(c.away?'away':c.free?'free':'working')),meter('Health',c.hp,c.max_hp),meter('Morale',c.morale,100));
      if(c.captured)card.append(node('span','Captured','citizen-state'));
      if(c.hp<c.max_hp)card.append(node('span','Injured','citizen-state'));
      card.addEventListener('click',()=>{selected=c.id;render();});return card;
    });
    grid.replaceChildren(...cards);if(!cards.length)grid.append(node('p','No citizens match this filter.'));
    if(focused)grid.querySelector('[data-portal-citizen="'+focused+'"]')?.focus({preventScroll:true});
    detail();
    if(focusedLink)[...contents.querySelectorAll('a')].find(a=>a.getAttribute('href')===focusedLink)?.focus({preventScroll:true});
  }
  window.addEventListener('citizen-portal',event=>{citizens=event.detail||[];render();});
  render();
})();
