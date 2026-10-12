// Reuse the original forms: one DOM node, one CSRF token, normal server validation.
function inspectableAnchor(href) {
  return typeof href==='string' && /^#(?:town-hall|(?:building|derelict|ruin)-[1-9]\d*)$/.test(href) ? href.slice(1) : null;
}
if (typeof module !== 'undefined') module.exports={inspectableAnchor};
if (typeof document !== 'undefined') (()=>{
  const map=document.querySelector('.map-scroll svg');
  const screen=document.getElementById('screen-build');
  if (!map || !screen) return;
  const inspector=document.createElement('aside');inspector.className='map-inspector';inspector.hidden=true;
  inspector.setAttribute('aria-label','Selected structure controls');
  const header=document.createElement('div');header.className='map-inspector-heading';
  const title=document.createElement('h3');title.textContent='Structure controls';
  const close=document.createElement('button');close.type='button';close.textContent='Close';
  const body=document.createElement('div');header.append(title,close);inspector.append(header,body);screen.append(inspector);
  let current=null,placeholder=null,previous=null,wasOpen=false;
  function dismiss(focus=true) {
    if (current && placeholder) {
      placeholder.replaceWith(current);
      if (current.tagName==='DETAILS') current.open=wasOpen;
    }
    current=null;placeholder=null;inspector.hidden=true;
    if (focus) previous?.focus({preventScroll:true});
  }
  close.addEventListener('click',()=>dismiss());
  document.addEventListener('keydown',event=>{
    if (event.key==='Escape' && !inspector.hidden) {event.preventDefault();dismiss();}
  });
  map.addEventListener('click',event=>{
    const link=event.target.closest('a');const id=inspectableAnchor(link?.getAttribute('href'));
    if (!id || map.closest('.map-scroll').dataset.pan==='true') return;
    const source=document.getElementById(id);if (!source) return;
    event.preventDefault();event.stopPropagation();dismiss(false);
    previous=link;current=source;wasOpen=source.tagName==='DETAILS' && source.open;
    placeholder=document.createComment('Map inspector original position');source.before(placeholder);
    body.append(source);
    if (source.tagName==='DETAILS') source.open=true;
    for (const details of source.querySelectorAll('details')) {
      if (details.querySelector('form')) details.open=true;
    }
    inspector.hidden=false;close.focus({preventScroll:true});
  });
  inspector.addEventListener('submit',event=>{
    const action=event.target.querySelector('input[name="action"]')?.value;
    if (action==='demolish' || action==='cancel_build') {
      const message=action==='demolish' ? 'Permanently demolish this building? Review the displayed refunds and consequences before continuing.' : 'Cancel this construction project? Review the displayed material recovery before continuing.';
      if (!window.confirm(message)) event.preventDefault();
    }
  });
})();
