// Presentation only: keep every original form and dashboard node in place.
const MENU_DEFAULTS={overview:'attention',economy:'market',social:'diplomacy'};
function preferredPane(items,key){return items.find(item=>item.id===MENU_DEFAULTS[key])||items[0];}
if(typeof module!=='undefined')module.exports={MENU_DEFAULTS,preferredPane};
if(typeof document!=='undefined')(()=>{
 const drawer=document.querySelector('.command-drawer');if(!drawer)return;
 const menus=[];
 for(const screen of document.querySelectorAll('.player-screen:not(#screen-build)')){
  const panes=[...screen.children].filter(node=>node.matches('.management-fold,.production-panel,.food-section,.citizens-panel,.military-board'));
  if(!panes.length)continue;
  const key=screen.id.replace('screen-','');screen.classList.add('menu-refined');
  const nav=document.createElement('nav');nav.className='menu-sections';nav.setAttribute('aria-label','Sections in this menu');
  const entries=panes.map((pane,index)=>{
   const section=pane.matches('.management-fold')?pane.querySelector('.production-panel,.food-section,.citizens-panel,.military-board'):pane;
   const target=section||pane;if(!target.id)target.id='menu-'+key+'-'+index;
   const title=target.querySelector('h2')?.textContent?.trim()||pane.querySelector('summary')?.textContent?.trim()||'Details';
   pane.classList.add('menu-pane');
   const link=document.createElement('a');link.href='#'+target.id;link.textContent=title;nav.append(link);
   return {id:target.id,pane,link};
  });
  let selected=preferredPane(entries,key);
  function show(entry){
   selected=entry;
   for(const item of entries){item.pane.hidden=item!==entry;if(item===entry){item.link.setAttribute('aria-current','page');if(item.pane.tagName==='DETAILS')item.pane.open=true;}else item.link.removeAttribute('aria-current');}
  }
  function sync(){
   let target=null;try{target=document.getElementById(decodeURIComponent(location.hash.slice(1)));}catch(_){}
   const entry=entries.find(item=>item.pane===target||item.pane.contains(target));
   show(entry||selected);
  }
  screen.prepend(nav);menus.push({screen,sync});sync();
 }
 function syncMenus(){
  const active=menus.find(menu=>!menu.screen.hidden);
  drawer.classList.toggle('menu-refined-window',Boolean(active));
  for(const menu of menus)menu.sync();
 }
 window.addEventListener('hashchange',syncMenus);
 for(const {screen} of menus)if(typeof MutationObserver!=='undefined')new MutationObserver(syncMenus).observe(screen,{attributes:true,attributeFilter:['hidden']});
 syncMenus();
})();
