// Small optional guidance; no requests, gameplay changes or modal overlay.
const GAMEPLAY_TIPS=[
  {id:'scavenge',text:'Scavenge derelict buildings to recover supplies. Click a ruin on the map to see its possible yields and assign free citizens.',link:'#scavenging',label:'Manage scavenging'},
  {id:'workers',text:'Most production buildings need assigned workers. An unstaffed building will not produce; passive storage and housing do not need operating workers.',link:'#screen-build',label:'Check buildings'},
  {id:'construction',text:'Construction and upgrades need a crew. New sites get one free citizen automatically when safe Oxygen coverage is available.',link:'#construction',label:'Build and upgrade'},
  {id:'storage',text:'Scrap, Metal and Electronics share storage. Food and Water each have their own capacity. A Full marker means it is time to use, sell or store more supplies.',link:'#construction',label:'Review storage'},
  {id:'oxygen',text:'Expand Oxygen coverage before placing distant buildings or assigning scavengers. Work outside Oxygen can harm citizens.',link:'#screen-build',label:'Check your map'},
  {id:'market',text:'Need supplies? Buy from shared market stock or your personal daily reserve. Sell surplus goods to earn Credits and free storage.',link:'#market',label:'Open market'},
  {id:'supplies',text:'Watch Food and Water net rates. A negative rate means stored supplies are shrinking; add production or obtain supplies before they run out.',link:'#needs',label:'Review supplies'},
  {id:'citizens',text:'Free citizens are unassigned people available for work. You can release a scavenger or another worker before assigning them elsewhere.',link:'#citizens',label:'View citizens'},
  {id:'upgrades',text:'Upgrades can increase output, storage or housing. Town Hall upgrades unlock more buildings. Check the next level’s costs and benefits first.',link:'#screen-build',label:'Review upgrades'},
  {id:'utilities',text:'Production may stop when a building lacks required Oxygen, electricity or input materials. Its status explains the problem.',link:'#screen-build',label:'Check building status'},
  {id:'map',text:'Click structures to inspect them. Use map filters to find unstaffed, stalled or damaged sites; enable pan mode to drag the map without placing buildings.',link:'#screen-build',label:'Open map'},
  {id:'combat',text:'Combat requires eligible citizens or ready equipment, an eligible target and a war declaration. Protection and the war warning can delay an attack.',link:'#conflict',label:'Review combat'},
  {id:'factory',text:'Military factories need staff, materials and compatible free equipment storage. Produce a small batch before ordering more.',link:'#manufacturing',label:'Review manufacturing'},
  {id:'attention',text:'Needs attention explains supply shortages and storage pressure, with links to actions that can help.',link:'#attention',label:'Review warnings'}
];
function tipDue(preferences,now) {
  const today=Math.floor(now/86400000);
  const count=preferences.day===today ? (preferences.count||0) : 0;
  return !preferences.disabled && count<3 &&
    (preferences.last==null || now-preferences.last>=600000);
}
function pickTip(tips,seen,random=Math.random) {
  const remaining=tips.filter(t=>!seen.includes(t.id));
  const pool=remaining.length ? remaining : tips;
  return pool[Math.min(pool.length-1,Math.floor(random()*pool.length))];
}
if(typeof module!=='undefined')module.exports={GAMEPLAY_TIPS,tipDue,pickTip};
if(typeof document!=='undefined')(()=>{
  const bar=document.querySelector('main > .resources');if(!bar)return;
  const key='settlement-game-tips:'+location.origin+':'+(bar.dataset.settlement||'local');
  let preferences={};try{preferences=JSON.parse(localStorage.getItem(key)||'{}')||{};}catch(_){}
  function save(){try{localStorage.setItem(key,JSON.stringify(preferences));}catch(_){} }
  const card=document.createElement('aside');card.className='gameplay-tip';card.hidden=true;
  card.setAttribute('role','dialog');card.setAttribute('aria-modal','false');card.setAttribute('aria-label','Gameplay tip');
  const heading=document.createElement('strong');heading.textContent='Gameplay tip';
  const text=document.createElement('p');text.setAttribute('aria-live','polite');const link=document.createElement('a');
  const controls=document.createElement('div');controls.className='tip-controls';
  const close=document.createElement('button');close.type='button';close.textContent='Close';
  const next=document.createElement('button');next.type='button';next.textContent='Next tip';
  const disable=document.createElement('button');disable.type='button';disable.textContent='Turn off automatic tips';
  controls.append(close,next,disable);card.append(heading,text,link,controls);document.body.append(card);
  function show(automatic=false){
    const tip=pickTip(GAMEPLAY_TIPS,Array.isArray(preferences.seen)?preferences.seen:[]);
    text.textContent=tip.text;link.href=tip.link;link.textContent=tip.label;
    const seen=Array.isArray(preferences.seen)?preferences.seen:[];
    preferences.seen=seen.length>=GAMEPLAY_TIPS.length ? [tip.id] : [...new Set([...seen,tip.id])];
    if(automatic){const day=Math.floor(Date.now()/86400000);preferences.count=(preferences.day===day?preferences.count||0:0)+1;preferences.day=day;}
    preferences.last=Date.now();save();card.hidden=false;
    disable.textContent=preferences.disabled?'Turn on automatic tips':'Turn off automatic tips';
  }
  function dismiss(){card.hidden=true;preferences.last=Date.now();save();}
  close.addEventListener('click',dismiss);
  link.addEventListener('click',dismiss);
  next.addEventListener('click',()=>show());
  disable.addEventListener('click',()=>{preferences.disabled=!preferences.disabled;save();card.hidden=true;});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!card.hidden)dismiss();});
  window.addEventListener('storage',event=>{
    if(event.key!==key)return;
    try{preferences=JSON.parse(event.newValue||'{}')||{};if(preferences.disabled)card.hidden=true;}catch(_){}
  });
  const toggle=document.createElement('button');toggle.type='button';toggle.className='tips-toggle';toggle.textContent='Gameplay tips';
  toggle.addEventListener('click',()=>{show();close.focus({preventScroll:true});});
  (document.querySelector('nav[aria-label="Player interaction"]')||bar.parentElement).append(toggle);
  function maybeShow(){
    const editing=['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName);
    const inspecting=document.querySelector('.map-inspector:not([hidden])');
    const urgent=document.querySelector('#resource-alert-list .attention-critical');
    if(!document.hidden&&!editing&&!inspecting&&!urgent&&card.hidden&&tipDue(preferences,Date.now()))show(true);
  }
  setTimeout(maybeShow,30000);setInterval(maybeShow,60000);
  window.addEventListener('storage-status',event=>{
    for(const [resource,status] of Object.entries(event.detail||{})){
      const marker=document.getElementById('storage-full-'+resource);if(!marker)continue;
      marker.hidden=!status.full;marker.title=status.description+' Add storage, use supplies or sell surplus.';
      marker.setAttribute('aria-label','Storage full. '+marker.title);
      marker.closest('.resource')?.classList.toggle('is-full',status.full);
    }
  });
})();
