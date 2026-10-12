// Viewport geometry changes presentation only; SVG coordinates remain map tiles.
function clampViewport(view, bounds) {
  const width = Math.max(Math.min(4,bounds.width),Math.min(bounds.width,view.width));
  const height = Math.max(Math.min(4,bounds.height),Math.min(bounds.height,view.height));
  return {x:Math.max(0,Math.min(bounds.width-width,view.x)),
    y:Math.max(0,Math.min(bounds.height-height,view.y)),width,height};
}
function frameZones(zones, bounds, padding=2) {
  if (!zones.length) return {x:0,y:0,...bounds};
  const left=Math.max(0,Math.min(...zones.map(r=>r.x))-padding);
  const top=Math.max(0,Math.min(...zones.map(r=>r.y))-padding);
  const right=Math.min(bounds.width,Math.max(...zones.map(r=>r.x+r.width))+padding);
  const bottom=Math.min(bounds.height,Math.max(...zones.map(r=>r.y+r.height))+padding);
  return clampViewport({x:left,y:top,width:right-left,height:bottom-top},bounds);
}
function scaledViewport(view, factor, bounds) {
  const width=Math.max(Math.min(4,bounds.width),Math.min(bounds.width,view.width*factor));
  const height=Math.max(Math.min(4,bounds.height),Math.min(bounds.height,view.height*factor));
  return clampViewport({x:view.x+(view.width-width)/2,y:view.y+(view.height-height)/2,width,height},bounds);
}
if (typeof module !== 'undefined') module.exports={clampViewport,frameZones,scaledViewport};
if (typeof document !== 'undefined') (() => {
  const container=document.querySelector('.map-scroll');
  const map=container?.querySelector('svg');
  if (!map) return;
  const bounds={width:map.viewBox.baseVal.width,height:map.viewBox.baseVal.height};
  const readRect=node=>({x:Number(node.getAttribute('x')),y:Number(node.getAttribute('y')),
    width:Number(node.getAttribute('width')),height:Number(node.getAttribute('height'))});
  const hallNode=map.querySelector('a[href="#town-hall"] > rect, g[data-inspection-hall] > rect');
  const oxygen=()=>frameZones([...map.querySelectorAll('.utility-zone,[data-utility="oxygen"]')].map(readRect),bounds);
  let view=oxygen(), pan=false, drag=null, suppressClick=false;
  const storageKey='map-viewport:'+document.title+(map.dataset.inspectionId || '');
  try {
    const saved=JSON.parse(sessionStorage.getItem(storageKey));
    if (saved && ['x','y','width','height'].every(k=>Number.isFinite(saved[k]))) view=clampViewport(saved,bounds);
  } catch (_) {}
  const controls=document.createElement('div'); controls.className='map-controls';
  controls.setAttribute('role','group'); controls.setAttribute('aria-label','Map zoom and movement');
  const status=document.createElement('p'); status.className='map-zoom-status';
  status.setAttribute('role','status');
  container.append(controls,status);
  function render() {
    map.setAttribute('viewBox',[view.x,view.y,view.width,view.height].join(' '));
    status.textContent=(bounds.width/view.width).toFixed(1)+'× · '+(pan ? 'Pan' : 'Place / inspect');
    status.title=pan ? 'Drag to move. Switch off Pan map to choose a building tile.' : 'Click land to place; click structures to inspect.';
    try { sessionStorage.setItem(storageKey,JSON.stringify(view)); } catch (_) {}
  }
  function button(label,action,icon=label) {
    const node=document.createElement('button'); node.type='button'; node.className='secondary';
    node.textContent=icon; node.title=label; node.setAttribute('aria-label',label); node.addEventListener('click',action); controls.append(node); return node;
  }
  window.addEventListener('map-preview-focus',event=>{
    const site=event.detail;
    if (site.x < view.x || site.y < view.y || site.x+site.width > view.x+view.width ||
        site.y+site.height > view.y+view.height) {
      view=frameZones([site],bounds,3);render();
    }
  });
  const zoom=factor=>{view=scaledViewport(view,factor,bounds);render();};
  const move=(dx,dy)=>{view=clampViewport({...view,x:view.x+dx*view.width,y:view.y+dy*view.height},bounds);render();};
  button('Zoom in',()=>zoom(.8),'+'); button('Zoom out',()=>zoom(1.25),'−');
  button('Full map',()=>{view={x:0,y:0,...bounds};render();},'▦');
  button('Oxygen area',()=>{view=oxygen();render();},'O₂');
  button('Town Hall',()=>{view=frameZones(hallNode ? [readRect(hallNode)] : [],bounds,3);render();},'⌂');
  const mode=button('Pan map',()=>{
    pan=!pan;container.dataset.pan=String(pan);mode.setAttribute('aria-pressed',String(pan));
    mode.title=pan ? 'Switch to placement / inspection' : 'Pan map';render();
  },'✥');
  mode.setAttribute('aria-pressed','false');
  window.addEventListener('map-build-open',()=>{if(pan)mode.click();});
  button('←',()=>move(-.25,0)).setAttribute('aria-label','Move map left');
  button('↑',()=>move(0,-.25)).setAttribute('aria-label','Move map up');
  button('↓',()=>move(0,.25)).setAttribute('aria-label','Move map down');
  button('→',()=>move(.25,0)).setAttribute('aria-label','Move map right');
  // Capture phase keeps pan gestures from triggering existing placement/inspection clicks.
  map.addEventListener('click',event=>{
    if (pan || suppressClick) {event.preventDefault();event.stopImmediatePropagation();suppressClick=false;}
  },true);
  map.addEventListener('pointerdown',event=>{
    if (!pan || event.button!==0) return;
    const matrix=map.getScreenCTM(); if (!matrix) return;
    suppressClick=false;
    drag={id:event.pointerId,x:event.clientX,y:event.clientY,view:{...view},inverse:matrix.inverse()};
    map.setPointerCapture(event.pointerId);event.preventDefault();
  });
  map.addEventListener('pointermove',event=>{
    if (!drag || drag.id!==event.pointerId) return;
    const first=new DOMPoint(drag.x,drag.y).matrixTransform(drag.inverse);
    const next=new DOMPoint(event.clientX,event.clientY).matrixTransform(drag.inverse);
    view=clampViewport({...drag.view,x:drag.view.x+first.x-next.x,y:drag.view.y+first.y-next.y},bounds);
    suppressClick=true;render();
  });
  for (const eventName of ['pointerup','pointercancel']) map.addEventListener(eventName,event=>{
    if (drag?.id!==event.pointerId) return;
    drag=null; if (map.hasPointerCapture(event.pointerId)) map.releasePointerCapture(event.pointerId);
  });
  container.addEventListener('keydown',event=>{
    const actions={'+':()=>zoom(.8),'=':()=>zoom(.8),'-':()=>zoom(1.25),
      ArrowLeft:()=>move(-.25,0),ArrowRight:()=>move(.25,0),ArrowUp:()=>move(0,-.25),ArrowDown:()=>move(0,.25),
      Home:()=>{view={x:0,y:0,...bounds};render();}};
    if (actions[event.key]) {event.preventDefault();actions[event.key]();}
  });
  container.addEventListener('wheel',event=>{
    if (!event.ctrlKey) return;event.preventDefault();zoom(event.deltaY>0 ? 1.25 : .8);
  },{passive:false});
  render();
})();
