// Map-first presentation only. Move existing controls; never clone or submit them.
const MAP_PURPOSES=[['Food','#7fae74'],['Water','#77a9cd'],['Oxygen','#63b6ac'],['Electricity','#d6b55f'],['Industry','#c89361'],['Housing','#c8bca2'],['Military','#b37b79'],['Storage','#9f8ab8'],['Support','#9ba8b4']];
function visibleCard(name,query){return String(name).toLowerCase().includes(String(query).trim().toLowerCase());}
function stateBadge(flags){return flags.damaged?['!','Damaged structure']:flags.stalled?['Ⅱ','Work is stalled']:flags.unstaffed?['○','Operating workers needed']:null;}
if(typeof module!=='undefined')module.exports={MAP_PURPOSES,visibleCard,stateBadge};
if(typeof document!=='undefined')(()=>{
  const main=document.getElementById('main'),map=document.querySelector('.map-panel');
  const screens=[...document.querySelectorAll('.player-screen')];
  if(!main||!map||!screens.length)return;
  document.body.classList.add('map-first');
  const shell=document.createElement('div');shell.className='command-shell';
  const drawer=document.createElement('aside');drawer.className='command-drawer';drawer.hidden=true;
  drawer.setAttribute('aria-label','Settlement management');drawer.setAttribute('role','dialog');drawer.setAttribute('aria-modal','false');
  const drawerHead=document.createElement('div');drawerHead.className='command-drawer-heading';
  const drawerTitle=document.createElement('strong');drawerTitle.textContent='Management';drawerTitle.id='management-window-title';drawer.setAttribute('aria-labelledby',drawerTitle.id);
  const close=document.createElement('button');close.type='button';close.textContent='Close ×';
  drawerHead.append(drawerTitle,close);drawer.append(drawerHead,...screens);
  const layout=map.closest('.settlement-layout');
  main.querySelector('.clock-controls').after(shell);shell.append(map,drawer);
  // Town Hall, long lists and legacy manual controls remain in the build panel.
  if(layout)layout.classList.add('manual-hall');
  const inspector=document.querySelector('.map-inspector');if(inspector)shell.append(inspector);
  const tools=document.createElement('div');tools.className='command-tools';
  const label=document.createElement('span');label.textContent=main.querySelector('.heading h1')?.textContent||'SETTLEMENT';
  const manual=document.createElement('button');manual.type='button';manual.textContent='Lists & manual controls';
  const rates=document.createElement('button');rates.type='button';rates.textContent='Resource rates';rates.setAttribute('aria-pressed','false');
  const attention=document.createElement('a');attention.href='#attention';attention.className='attention-shortcut';attention.textContent='Needs attention';
  const work=document.createElement('details');work.className='work-shortcut';const workTitle=document.createElement('summary');workTitle.textContent='Active work';const workList=document.createElement('div');work.append(workTitle,workList);
  const legend=document.createElement('details');legend.className='purpose-legend';
  const summary=document.createElement('summary');summary.textContent='Map key';legend.append(summary);
  const key=document.createElement('div');
  for(const [name,color] of MAP_PURPOSES){const item=document.createElement('span'),dot=document.createElement('i');dot.style.backgroundColor=color;item.append(dot,document.createTextNode(name));key.append(item);}
  const note=document.createElement('p');note.textContent='Gold: Town Hall. Dashed grey: derelict. Primary colour stays during construction. ! damage · ○ needs workers · Ⅱ stalled. Green %: building work; amber pickaxe/bar: scavenging. Dashed areas: utilities.';
  key.append(note);legend.append(key);tools.append(label,manual,work,attention,legend);shell.before(tools);
  map.querySelector('.map-legend')?.setAttribute('hidden','');
  // One compact account/help menu replaces repeated navigation above the map.
  const account=document.createElement('details');account.className='account-tools';
  const accountSummary=document.createElement('summary');accountSummary.textContent='Account & help';const accountBody=document.createElement('div');account.append(accountSummary,accountBody);
  for(const node of [...main.children]){
    if(node.matches('nav:not(.player-menu)') || node.matches('.building-controls')&&node.querySelector('form[action="/logout"]') || node.matches('p')&&node.querySelector('#overall-score'))accountBody.append(node);
  }
  tools.append(account);
  const clock=main.querySelector('.clock-controls');
  if(clock){clock.classList.add('compact-clock');label.after(clock);}
  // Keep the historical offline explanation available without a permanent banner.
  for(const paragraph of [...main.querySelectorAll('p.attention-warning')]){
    if(paragraph.textContent.trim().startsWith('Offline simulation is capped at'))accountBody.append(paragraph);
  }
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>fitMap()).observe(tools);
  const dock=document.querySelector('.player-menu');
  if(dock){
    document.body.append(dock);

  }
  function fitMap(){shell.style.height=Math.max(260,window.innerHeight-shell.getBoundingClientRect().top-(dock?.getBoundingClientRect().height||58)-18)+'px';}
  window.addEventListener('resize',fitMap);requestAnimationFrame(fitMap);
  const resources=main.querySelector(':scope > .resources');
  const resourcePaths=['M3 20C3 8 10 3 21 3c0 11-5 18-18 17ZM4 19l12-11','M12 2C9 7 4 12 4 16a8 8 0 0 0 16 0c0-4-5-9-8-14Z','M4 5h16v15H4zM8 2v6M16 2v6','M3 7l9-4 9 4v12l-9 3-9-3ZM3 7l9 5 9-5M12 12v10','M6 6h12v12H6zM2 8h4M18 8h4M8 2v4M8 18v4M16 2v4M16 18v4','M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM15 7h-4a3 3 0 0 0 0 6h2a3 3 0 0 1 0 6H9M12 4v16','M8 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6M2 21v-4a6 6 0 0 1 12 0v4M16 5h6M16 11h6','M8 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6M2 21v-4a6 6 0 0 1 12 0v4M16 16l3 3 4-6','M12 2l8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4'];
  [...resources?.children||[]].forEach((resource,index)=>{resource.tabIndex=0;const label=resource.querySelector('span');resource.setAttribute('aria-label',label?.textContent||'Resource');const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.classList.add('resource-label-icon');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',resourcePaths[index]||resourcePaths[0]);icon.append(path);label?.prepend(icon);});
  function sizeBar(){document.documentElement.style.setProperty('--resource-bar-height',(resources?.getBoundingClientRect().height||70)+'px');fitMap();}
  if(typeof ResizeObserver!=='undefined'&&resources)new ResizeObserver(sizeBar).observe(resources);
  sizeBar();window.addEventListener('resize',sizeBar);
  rates.addEventListener('click',()=>{const expanded=rates.getAttribute('aria-pressed')!=='true';rates.setAttribute('aria-pressed',String(expanded));resources?.classList.toggle('show-rates',expanded);sizeBar();});
  let manualOpen=false;
  function sync(){
    const selected=screens.find(node=>!node.hidden);const build=selected?.id==='screen-build';
    drawer.hidden=build&&!manualOpen;shell.classList.toggle('has-drawer',!drawer.hidden);
    drawerTitle.textContent=({ 'screen-overview':'Settlement overview','screen-build':'Buildings & work','screen-citizens':'Citizens','screen-economy':'Economy & market','screen-military':'Military','screen-social':'Diplomacy & messages' })[selected?.id]||'Settlement management';
    manual.setAttribute('aria-expanded',String(manualOpen&&!drawer.hidden));
    window.dispatchEvent(new Event('resize'));
  }
  close.addEventListener('click',()=>{manualOpen=false;location.hash='screen-build';sync();manual.focus({preventScroll:true});});
  manual.addEventListener('click',()=>{manualOpen=!manualOpen;location.hash='screen-build';sync();});
  document.querySelector('.player-menu')?.addEventListener('click',event=>{
    const link=event.target.closest('a');if(!link)return;
    if(!drawer.hidden && link.hash===location.hash){event.preventDefault();event.stopImmediatePropagation();close.click();return;}
    manualOpen=false;setTimeout(()=>{sync();if(!drawer.hidden)close.focus({preventScroll:true});},0);
  },true);
  window.addEventListener('hashchange',()=>{
    let target=null;try{target=document.getElementById(decodeURIComponent(location.hash.slice(1)));}catch(_){}
    if(target?.closest('#screen-build')&&target.id!=='screen-build'){manualOpen=true;target.hidden=false;}
    sync();
  });
  document.addEventListener('keydown',event=>{if(!event.defaultPrevented&&event.key==='Escape'&&!drawer.hidden){manualOpen=false;location.hash='screen-build';sync();}});
  // Supplement visual portals with collapsed, searchable manual lists.
  for(const screen of screens){
    for(const section of [...screen.children]){
      if(!section.matches('.production-panel,.food-section,.citizens-panel,.settlement-layout'))continue;
      if(section.id==='attention')continue;
      if(section.id==='citizens'){
        const table=section.querySelector('.table-scroll');if(table){const details=document.createElement('details'),s=document.createElement('summary');s.textContent='Manual citizen roster';table.before(details);details.append(s,table);}continue;
      }
      if(section.classList.contains('settlement-layout')&&!section.querySelector('#town-hall'))continue;
      const fold=document.createElement('details');fold.className='management-fold';
      const s=document.createElement('summary');s.textContent=section.querySelector('h2')?.textContent||'Town Hall & manual controls';
      section.before(fold);fold.append(s,section);
    }
    const cards=[...screen.querySelectorAll('.food-card,.work-card')];
    if(cards.length){const search=document.createElement('input');search.type='search';search.placeholder='Find a building or work site';search.setAttribute('aria-label','Filter manual building and work lists');search.addEventListener('input',()=>cards.forEach(card=>{card.hidden=!visibleCard(card.textContent,search.value);}));screen.prepend(search);}
  }
  const svg=map.querySelector('svg');
  function attentionCount(){const count=document.querySelectorAll('#resource-alert-list li').length;attention.textContent=count?'Needs attention · '+count:'No supply alerts';attention.classList.toggle('has-alerts',count>0);}
  const alerts=document.getElementById('resource-alert-list');if(alerts&&typeof MutationObserver!=='undefined')new MutationObserver(attentionCount).observe(alerts,{childList:true});attentionCount();
  function workItems(){
    workList.replaceChildren();
    for(const marker of svg.querySelectorAll('[id^="map-job-"],[id^="map-scavenging-"]')){
      const structure=marker.closest('a');if(!structure)continue;const link=document.createElement('a');link.href=structure.getAttribute('href');
      link.textContent=(structure.querySelector('title')?.textContent||'Work site')+' · '+(marker.getAttribute('aria-label')||marker.textContent);workList.append(link);
    }
    for(const [href,text] of [['#scavenging','Scavenging yields & crews'],['#expeditions','Expeditions & recall'],['#conflict','Combat missions & reports']]){const link=document.createElement('a');link.href=href;link.textContent=text;workList.append(link);}
  }
  work.addEventListener('toggle',()=>{if(work.open)workItems();});
  function badges(){
    for(const node of svg.querySelectorAll('[data-map-key]')){
      node.querySelector('.map-state-badge')?.remove();
      if(node.dataset.mapKey.startsWith('derelict-'))continue;
      const badge=stateBadge({damaged:node.dataset.damaged==='1',stalled:node.dataset.stalled==='1',unstaffed:node.dataset.unstaffed==='1'});
      const rect=node.querySelector('rect');if(!badge||!rect)continue;
      const text=document.createElementNS('http://www.w3.org/2000/svg','text');text.classList.add('map-state-badge');
      text.setAttribute('x',Number(rect.getAttribute('x'))+Number(rect.getAttribute('width'))+.1);text.setAttribute('y',Number(rect.getAttribute('y'))+.4);text.setAttribute('pointer-events','none');text.textContent=badge[0];
      const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=badge[1];text.append(title);node.append(text);
    }
  }
  svg.addEventListener('click',event=>{const node=event.target.closest('a');if(!node||map.querySelector('.map-scroll').dataset.pan==='true')return;if(!drawer.hidden){manualOpen=false;location.hash='screen-build';sync();}svg.querySelector('.map-selected')?.classList.remove('map-selected');node.classList.add('map-selected');const id=node.getAttribute('href')?.slice(1);const source=id&&document.getElementById(id);if(source)source.hidden=false;});
  window.addEventListener('map-filter-state',()=>{badges();if(work.open)workItems();});badges();if(!location.hash){location.replace('#screen-build');}sync();
})();
