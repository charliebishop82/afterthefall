// Military portal draft: links to existing forms, no alternate action routes.
function equipmentMatches(row,filter){return filter==='all'||filter==='ready'&&row.ready>0||filter==='deployed'&&row.deployed>0||filter==='damaged'&&row.damaged>0;}
if(typeof module!=='undefined')module.exports={equipmentMatches};
if(typeof document!=='undefined')(()=>{
  const screen=document.getElementById('screen-military');const seed=document.getElementById('military-portal-data');
  if(!screen||!seed)return;
  let state;try{state=JSON.parse(seed.dataset.dashboard);}catch(_){return;}
  let filter='all',selected=null;
  const board=document.createElement('section');board.className='military-board';
  const title=document.createElement('h2');title.textContent='Military overview';
  const intro=document.createElement('p');intro.textContent='Inspect equipment and operations here. Quick links open the existing manual controls below.';
  const navigation=document.createElement('nav');navigation.className='military-quick-links';navigation.setAttribute('aria-label','Military actions');
  for(const [href,label] of [['#military','Produce equipment'],['#conflict','Declare war / launch raid'],['#expeditions','Explore the Wastes'],['#support','Patrols / guards'],['#maintenance','Repair drones']]){
    const a=document.createElement('a');a.href=href;a.textContent=label;navigation.append(a);
  }
  const stats=document.createElement('div');stats.className='military-stats';
  const filters=document.createElement('div');filters.className='military-filters';
  for(const [key,label] of [['all','All equipment'],['ready','Ready'],['deployed','Deployed'],['damaged','Damaged']]){
    const b=document.createElement('button');b.type='button';b.textContent=label;b.dataset.filter=key;
    b.addEventListener('click',()=>{filter=key;render();});filters.append(b);
  }
  const grid=document.createElement('div');grid.className='military-grid';
  const operations=document.createElement('div');operations.className='military-operations';
  const inspector=document.createElement('aside');inspector.className='military-inspector';inspector.hidden=true;inspector.setAttribute('aria-label','Selected equipment');
  const detail=document.createElement('div');const close=document.createElement('button');close.type='button';close.textContent='Close details';
  function dismiss(){const previous=selected;selected=null;inspector.hidden=true;grid.querySelector('[data-equipment-kind="'+previous+'"]')?.focus({preventScroll:true});}
  close.addEventListener('click',dismiss);inspector.append(detail,close);
  board.append(title,intro,navigation,stats,filters,grid,operations,inspector);screen.prepend(board);
  function node(tag,text){const e=document.createElement(tag);e.textContent=text;return e;}
  function link(href,text){const a=node('a',text);a.href=href;return a;}
  function inspect(){
    const row=state.equipment.find(r=>r.kind===selected);inspector.hidden=!row;if(!row)return;
    detail.replaceChildren(node('h3',row.name),node('p',row.ready+' ready · '+row.deployed+' deployed · '+row.damaged+' damaged'));
    if(row.ammunition)detail.append(node('p',row.ammunition+' stored rounds. Reserved/deployed rounds are not ready stock.'));
    for(const unit of row.units){
      detail.append(node('p','#'+unit.id+' · '+unit.status+' · '+unit.hp.toFixed(1)+' / '+unit.max_hp+' HP · '+(unit.ready?'Ready':'Not ready')));
      if(unit.home)detail.append(link('#building-'+unit.home,'Inspect home building #'+unit.home));
    }
    detail.append(link('#military','Production and storage controls'),document.createElement('br'),link('#maintenance','Servicing and repair controls'));
  }
  function render(){
    stats.replaceChildren(...[['Citizen raiders',state.eligible_raiders],['Attack allowance',state.allowance],['Home citizens',state.home],['Patrols / guards',state.patrols+' / '+state.guards]].map(([label,value])=>{
      const box=document.createElement('div');box.append(node('strong',String(value)),node('span',label));return box;
    }));
    for(const b of filters.children)b.setAttribute('aria-pressed',String(b.dataset.filter===filter));
    const focus=document.activeElement?.dataset.equipmentKind;
    const focusLink=inspector.contains(document.activeElement)?document.activeElement.getAttribute('href'):null;
    grid.replaceChildren(...state.equipment.filter(r=>equipmentMatches(r,filter)).map(row=>{
      const card=document.createElement('button');card.type='button';card.className='military-card';card.dataset.equipmentKind=row.kind;
      card.setAttribute('aria-pressed',String(selected===row.kind));
      card.append(node('span',row.kind.includes('drone')?'◇':'▰'),node('strong',row.name),node('span',row.ready+' ready / '+row.total+' total'),node('small',row.deployed+' deployed · '+row.damaged+' damaged'));
      card.addEventListener('click',()=>{selected=row.kind;render();});return card;
    }));
    if(!grid.children.length)grid.append(node('p',state.equipment.length?'No equipment matches this filter.':'Enable military production using the controls below.'));
    if(focus)grid.querySelector('[data-equipment-kind="'+focus+'"]')?.focus({preventScroll:true});
    operations.replaceChildren(node('h3','Production and active operations'));
    if(state.jobs.length)for(const job of state.jobs)operations.append(node('p','Batch #'+job.id+' · '+job.kind.replaceAll('_',' ')+' · '+job.status+' · '+Math.round(job.percent)+'%'+(job.reason?' — '+job.reason:'')));
    else operations.append(node('p','No active production batches.'));
    for(const trip of state.expeditions)operations.append(link('#expeditions','Expedition #'+trip.id+' · '+trip.status+' · '+Math.ceil(trip.seconds/60)+' min to return · '+trip.crew.join(', ')),document.createElement('br'));
    for(const [id,seconds] of Object.entries(state.raid_timers||{}))operations.append(link('#conflict','Raid #'+id+' · '+Math.ceil(seconds/60)+' min remaining'),document.createElement('br'));
    operations.append(node('p','Citizen raids keep '+state.home_minimum+' citizens at home. Protection and war warnings can block attacks. Ground defense in the resource bar describes local defense; it does not predict an attack result.'));
    inspect();
    if(focusLink)[...detail.querySelectorAll('a')].find(a=>a.getAttribute('href')===focusLink)?.focus({preventScroll:true});
  }
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!inspector.hidden)dismiss();});
  window.addEventListener('military-portal',event=>{state=event.detail;render();});render();
})();
