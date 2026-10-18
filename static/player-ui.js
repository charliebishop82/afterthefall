// Focused menu views preserve all existing forms, IDs and live refresh hooks.
function menuCategory(id,heading,isBuilding=false) {
  // Explicit system IDs win over words like Citizen in a combat heading.
  if (['conflict','military','maintenance','expeditions'].includes(id) || /Structural combat/.test(heading)) return 'military';
  if (isBuilding || ['construction','scavenging'].includes(id) || /Scavenging|Destroyed buildings|Support and defense/.test(heading)) return 'build';
  if (id==='citizens' || /Housing|Citizen/.test(heading)) return 'citizens';
  if (['trading','market','bank','needs'].includes(id)) return 'economy';
  if (['messages','board','diplomacy'].includes(id) || /Public news|Your notifications/.test(heading)) return 'social';
  return 'overview';
}
const NAV_ICONS={
  overview:'M3 10l9-7 9 7 M5 9v12h14V9 M9 21v-7h6v7',
  build:'M4 20l9-9 M11 4l3-2 8 8-3 3-8-9 M2 18l4 4',
  citizens:'M8 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6 M2 21v-4a6 6 0 0 1 12 0v4 M16 4a3 3 0 0 1 0 6 M17 13a5 5 0 0 1 5 5v3',
  economy:'M3 7h17l-4-4 M21 17H4l4 4',
  military:'M12 2l8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4 M8 12l3 3 5-6',
  social:'M3 5h18v14H3z M3 5l9 8 9-8'
};
const NAV_LABELS={overview:'Overview',build:'Build',citizens:'Citizens',economy:'Economy',military:'Military',social:'Diplomacy'};
if (typeof module !== 'undefined') module.exports={menuCategory,NAV_ICONS,NAV_LABELS};
if (typeof document !== 'undefined') (() => {
  const main = document.getElementById('main');
  if (!main || !main.querySelector('.clock-controls')) return;
  const views = [
    ['overview','Overview'], ['build','Build & Buildings'], ['citizens','Citizens'],
    ['economy','Economy & Trade'], ['military','Military'], ['social','Diplomacy & Messages']
  ];
  const groups = new Map(views.map(([key]) => {
    const section = document.createElement('div');
    section.className = 'player-screen'; section.id = 'screen-'+key;
    return [key,section];
  }));
  const menu = document.createElement('nav');
  document.body.classList.add('has-player-dock');
  menu.className = 'player-menu'; menu.setAttribute('aria-label','Game pages');
  for (const [key,label] of views) {
    const link = document.createElement('a'); link.href = '#screen-'+key;
    link.setAttribute('aria-label',label);link.title=label;
    const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
    icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');icon.setAttribute('focusable','false');
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',NAV_ICONS[key]);icon.append(path);
    const text=document.createElement('span');text.textContent=NAV_LABELS[key];link.append(icon,text);menu.append(link);
  }
  function category(element) {
    return menuCategory(element.id,element.querySelector('h2')?.textContent || '',
      element.matches('.settlement-layout,.food-section'));
  }
  // Explanations are collapsed; warnings, live statuses and action confirmations stay visible.
  for (const node of main.querySelectorAll('p.small-note,p.map-help,.clock-controls > div > p,.staffing > p,#construction .building-controls > p:first-child,#trading > p:first-of-type,#market > p:first-of-type,#diplomacy > p:first-of-type,#messages > p:first-of-type,#support > p:first-of-type,#military > p:first-of-type,#military > p:nth-of-type(2),#conflict > p:first-of-type,#maintenance > p:first-of-type')) {
    if (node.closest('details') || node.closest('form') || node.querySelector('input,button,select') || /confirm|permanent|cancel|danger/i.test(node.textContent)) continue;
    const info = document.createElement('details'); info.className = 'player-info';
    const summary = document.createElement('summary'); summary.textContent = 'How this works';
    node.before(info); info.append(summary,node);
  }
  // Fold supplementary static explanations; keep warnings, rates and forms intact.
  const helpHeadings=new Set(['Citizen progression','Structural combat']);
  for (const section of main.querySelectorAll('section')) {
    if (!helpHeadings.has(section.querySelector('h2')?.textContent)) continue;
    const paragraphs=[...section.querySelectorAll('p')].filter(p=>!p.closest('form,details') &&
      !p.matches('.error,[role="alert"],[role="status"]'));
    if (!paragraphs.length) continue;
    const details=document.createElement('details');details.className='player-info';
    const summary=document.createElement('summary');summary.textContent='Rules & details';
    paragraphs[0].before(details);details.append(summary,...paragraphs);
  }
  const catalogue = main.querySelector('#construction .table-scroll');
  if (catalogue) {
    const details = document.createElement('details'); details.className = 'player-info';
    const summary = document.createElement('summary'); summary.textContent = 'Building costs, benefits & unlocks';
    catalogue.before(details); details.append(summary,catalogue);
  }
  for (const element of [...main.children]) {
    if (element.matches('section:not(.heading):not(.resources):not(.clock-controls),.settlement-layout')) {
      groups.get(category(element)).append(element);
    }
  }
  main.querySelector('nav[aria-label="Player interaction"]')?.remove();
  main.querySelector('.clock-controls').after(menu);
  for (const section of groups.values()) main.append(section);
  // Keep the build workflow in a useful order: map, placement, buildings, scavenging.
  const buildScreen=groups.get('build');
  const buildings=buildScreen.querySelector('.food-section');
  const scavenging=buildScreen.querySelector('#scavenging');
  if (buildings && scavenging) buildings.after(scavenging);
  // Building condition/output stays visible; management forms are opened on demand.
  for (const card of main.querySelectorAll('.food-card')) {
    const controls=card.querySelector('.building-controls'); if (!controls) continue;
    const details=document.createElement('details'); details.className='player-info';
    const summary=document.createElement('summary'); summary.textContent='Staffing, upgrades & repairs';
    controls.before(details);details.append(summary,controls);
  }
  const descriptions={
    overview:'Supply balance and advice.',
    build:'Place structures, manage crews and recover supplies.',
    citizens:'Housing, health and resident policies.',
    economy:'Rations, shared markets, private trades and banking.',
    military:'Manufacturing, repairs, raids and defenses.',
    social:'Treaties, private messages and settlement news.'
  };
  for (const [key,screen] of groups) {
    const intro=document.createElement('p'); intro.className='screen-intro';intro.textContent=descriptions[key];
    const shortcuts=document.createElement('nav');shortcuts.className='section-shortcuts';
    shortcuts.setAttribute('aria-label','Sections on this page');
    [...screen.children].forEach((section,index)=>{
      const heading=section.querySelector('h2');if (!heading) return;
      if (!section.id) section.id='section-'+key+'-'+index;
      const link=document.createElement('a');link.href='#'+section.id;link.textContent=heading.textContent;
      shortcuts.append(link);
    });
    screen.prepend(intro,shortcuts);
  }
  function show() {
    let target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); }
    catch (_) { target = null; }
    let selected = target?.closest('.player-screen');
    if (!selected) {
      let saved;
      try { saved = sessionStorage.getItem('player-screen'); } catch (_) {}
      selected = groups.get(saved) || groups.get('build');
    }
    for (const [key,section] of groups) {
      section.hidden = section !== selected;
      const link = menu.querySelector('a[href="#screen-'+key+'"]');
      if (section === selected) link.setAttribute('aria-current','page');
      else link.removeAttribute('aria-current');
    }
    try { sessionStorage.setItem('player-screen',selected.id.slice(7)); } catch (_) {}
    if (target && target !== selected) {
      for (let ancestor = target; ancestor && ancestor !== main; ancestor = ancestor.parentElement) {
        if (ancestor.tagName === 'DETAILS') ancestor.open = true;
      }
      target.scrollIntoView({block:'start'});
    }
  }
  window.addEventListener('hashchange',show); show();
  try {
    const saved = sessionStorage.getItem('panel-scroll');
    sessionStorage.removeItem('panel-scroll');
    if (saved) {
      const position = JSON.parse(saved);
      [...document.querySelectorAll('details')].forEach((node,index) => {
        node.open = Boolean(position.details[index]);
      });
      const map = document.querySelector('.map-scroll');
      if (map) { map.scrollLeft = position.mapX; map.scrollTop = position.mapY; }
      requestAnimationFrame(() => requestAnimationFrame(() => scrollTo(position.x,position.y)));
    }
  } catch (_) {}
})();
