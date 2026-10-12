// Move the original construction controls: one form, one token, one set of IDs.
function nextBuildRotation(value){return String(value)==='90'?'0':'90';}
if(typeof module!=='undefined')module.exports={nextBuildRotation};
if(typeof document!=='undefined')(()=>{
  const scroller=document.querySelector('.map-scroll');
  const kind=document.getElementById('building-type');
  const rotation=document.getElementById('build-rotation');
  const form=kind?.closest('form');const panel=scroller?.closest('.map-panel');
  if(!scroller||!panel||!form||!rotation)return;
  const requirements=document.getElementById('build-requirements')?.closest('details');
  const button=document.createElement('button');button.type='button';button.className='map-build-button';
  button.textContent='⚒';button.title='Build on the map';button.setAttribute('aria-label','Open map building controls');
  button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','map-build-panel');
  const drawer=document.createElement('aside');drawer.className='map-build-panel';drawer.id='map-build-panel';drawer.hidden=true;
  drawer.setAttribute('aria-label','Build on the map');
  const heading=document.createElement('div');heading.className='map-build-heading';
  const title=document.createElement('strong');title.textContent='Build on the map';
  const close=document.createElement('button');close.type='button';close.textContent='Close';
  heading.append(title,close);
  const hint=document.createElement('p');hint.textContent='Choose a building, rotate if needed, then click empty land to position its footprint. Start construction confirms the selected site.';
  const body=document.createElement('div');
  const rotate=document.createElement('button');rotate.type='button';rotate.textContent='↻ Rotate 90°';
  drawer.append(heading,hint,rotate,body);panel.append(button,drawer);
  let formPlaceholder=null,requirementsPlaceholder=null;
  function position(){button.style.top=(scroller.offsetTop+10)+'px';drawer.style.top=(scroller.offsetTop+50)+'px';}
  function dismiss(focus=true){
    if(formPlaceholder){formPlaceholder.replaceWith(form);formPlaceholder=null;}
    if(requirementsPlaceholder){requirementsPlaceholder.replaceWith(requirements);requirementsPlaceholder=null;}
    drawer.hidden=true;button.setAttribute('aria-expanded','false');
    scroller.dataset.buildOverlay='false';
    if(focus)button.focus({preventScroll:true});
  }
  function open(){
    if(!drawer.hidden){dismiss();return;}
    document.querySelector('.map-inspector:not([hidden]) .map-inspector-heading button')?.click();
    formPlaceholder=document.createComment('Original build form position');form.before(formPlaceholder);body.append(form);
    if(requirements){requirementsPlaceholder=document.createComment('Original requirements position');requirements.before(requirementsPlaceholder);body.append(requirements);}
    drawer.hidden=false;button.setAttribute('aria-expanded','true');scroller.dataset.buildOverlay='true';
    // Disable pan so clicking land places the preview rather than dragging it.
    window.dispatchEvent(new CustomEvent('map-build-open'));
    position();kind.focus({preventScroll:true});
  }
  button.addEventListener('click',open);close.addEventListener('click',()=>dismiss());
  rotate.addEventListener('click',()=>{rotation.value=nextBuildRotation(rotation.value);rotation.dispatchEvent(new Event('change',{bubbles:true}));});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!drawer.hidden)dismiss();});
  scroller.querySelector('svg')?.addEventListener('click',event=>{
    if(!drawer.hidden&&event.target.closest('a'))dismiss(false);
  });
  window.addEventListener('resize',position);if(typeof ResizeObserver!=='undefined')new ResizeObserver(position).observe(panel);
  position();
})();
